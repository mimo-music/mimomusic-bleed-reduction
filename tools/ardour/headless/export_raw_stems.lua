-- SPDX-License-Identifier: GPL-3.0-or-later
-- SPDX-FileCopyrightText: 2026 Mettronic GmbH

-- export_raw_stems.lua -- every track of an Ardour session as an unprocessed stem
-- (as they are recorded, in the format Ardour stores them; for the Bleed Reduction import).
--
--   sh tools/export_raw_stems.sh <session folder> <output folder>    (Ardour closed)
--
-- Runs in ardour9-lua (Ardour's own engine, no window). For each audio track: Ardour's
-- "bounce without processing" of the session range: the playlist as edited (the takes,
-- region gain, fades, muted regions left out), no plugins, no sends, no fader, no pan, no
-- track mute; in the session's own file format (sample format and header as recorded).
-- One file per channel, as Ardour stores them: "NN <track>.wav", stereo "NN <track>-L.wav" / "-R.wav".
-- The bounces are written into the session and moved out (copied when the output is on another
-- drive); the session is closed WITHOUT saving. export_raw_stems.sh gives it a stand-in copy of
-- the session in a temporary folder, so the real one is only read.
-- Arguments come in the environment: BLEED_SESSION_DIR, BLEED_SESSION_NAME, BLEED_OUT.

local function log (...) local t = {} for _, v in ipairs ({...}) do t[#t+1] = tostring (v) end io.stderr:write (table.concat (t, " ") .. "\n") end

local dir, name, out = os.getenv ("BLEED_SESSION_DIR"), os.getenv ("BLEED_SESSION_NAME"), os.getenv ("BLEED_OUT")
if not dir or not name or not out then log ("ERROR: BLEED_SESSION_DIR, BLEED_SESSION_NAME, BLEED_OUT needed") os.exit (2) end

local function safe (s) return (s:gsub ("[/\\:%*%?\"<>|]", "_")) end

local function copy_file (src, dst)
	local i, ierr = io.open (src, "rb")
	if not i then return false, ierr end
	local o, oerr = io.open (dst, "wb")
	if not o then i:close () return false, oerr end
	while true do
		local b = i:read (4 * 1024 * 1024)
		if not b then break end
		local w, werr = o:write (b)
		if not w then i:close () o:close () return false, werr end
	end
	i:close ()
	local c, cerr = o:close ()
	if not c then return false, cerr end
	return true
end

AudioEngine:set_backend ("None (Dummy)", "", "")
Session = load_session (dir, name)
if not Session then log ("ERROR: could not open the session " .. dir .. " / " .. name) os.exit (3) end

local failed = false
local ok, err = pcall (function ()
	-- the range: the session range, else from the first to the last region
	local s0, s1 = Session:current_start_sample (), Session:current_end_sample ()
	if s1 <= s0 then
		s0, s1 = nil, nil
		for route in Session:get_tracks ():iter () do
			for r in route:to_track ():playlist ():region_list ():iter () do
				local a, b = r:position ():samples (), (r:position () + r:length ()):samples ()
				if not s0 or a < s0 then s0 = a end
				if not s1 or b > s1 then s1 = b end
			end
		end
	end
	if not s0 then error ("the session has no regions") end
	local rate = Session:nominal_sample_rate ()
	log (string.format ("range %d - %d (%.1f s at %d Hz)", s0, s1, (s1 - s0) / rate, rate))

	local proc = ARDOUR.LuaAPI.nil_proc ()          -- bounce without processing
	local tracks = {}
	for route in Session:get_tracks ():iter () do tracks[#tracks + 1] = route end
	-- as in the editor (presentation order); unknown -> as listed
	local function order (r)
		for _, f in ipairs ({function () return r:presentation_info_ptr ():order () end}) do
			local ok, o = pcall (f)
			if ok and o then return o end
		end
		return nil
	end
	local pos = {}
	for i, r in ipairs (tracks) do pos[r:name ()] = i end
	table.sort (tracks, function (a, b) return (order (a) or pos[a:name ()]) < (order (b) or pos[b:name ()]) end)
	local n = 0
	for i, route in ipairs (tracks) do
		local t = route:to_track ()
		local pl = t:playlist ()
		if pl:data_type ():to_string () ~= "audio" then
			log (string.format ("skip %s: not audio", route:name ()))
		elseif pl:region_list ():size () == 0 then
			log (string.format ("skip %s: no regions", route:name ()))
		elseif not t:bounceable (proc, false) then
			log (string.format ("skip %s: can't be bounced (inactive?)", route:name ()))
		else
			local r = t:bounce_range (s0, s1, ARDOUR.InterThreadInfo (), proc, false, "bleed_raw_" .. safe (route:name ()), false)
			if r:isnil () then error ("bounce failed: " .. route:name ()) end
			local nch = r:to_audioregion ():n_channels ()
			local base = string.format ("%02d %s", i, safe (route:name ()))
			for c = 0, nch - 1 do
				local src = r:source (c):to_filesource ():path ()
				local suffix = nch == 1 and "" or nch == 2 and (c == 0 and "-L" or "-R") or string.format ("-%d", c + 1)
				local ext = src:match ("(%.[^./]+)$") or ".wav"
				local dst = out .. "/" .. base .. suffix .. ext
				local moved, merr = os.rename (src, dst)
				if not moved then
					-- another drive (rename can't cross devices): copy, then the bounce out of the session
					local copied, cerr = copy_file (src, dst)
					os.remove (src)
					if not copied then os.remove (dst) error ("could not move " .. src .. " to " .. dst .. ": " .. tostring (merr) .. " / " .. tostring (cerr)) end
				end
				log (string.format ("%s%s: %s", route:name (), suffix, dst))
			end
			n = n + 1
		end
	end
	log (string.format ("DONE: %d tracks exported to %s", n, out))
end)
if not ok then log ("ERROR: " .. tostring (err)) failed = true end
-- no save: the session stays as it was
Session:close ()
if failed then os.exit (1) end
