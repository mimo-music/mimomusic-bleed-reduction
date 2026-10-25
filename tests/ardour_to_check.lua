-- SPDX-License-Identifier: GPL-3.0-or-later
-- SPDX-FileCopyrightText: 2026 Mettronic GmbH

-- ardour_to_check.lua -- what Ardour sees in a session after tools/to_ardour.py
-- (run by tests/ardour_to_test.sh): per track one line
--   TRACK <name>|<order>|<muted>|<inputs>|<gain>|<plugins>|<outputs connected>
--   REGION <track>|<position>|<length>|<channels>|<source>@<natural position>,...
-- Closed without saving. Session folder and name in BLEED_TEST_DIR, BLEED_TEST_NAME.
io.stdout:setvbuf ("no")
AudioEngine:set_backend ("None (Dummy)", "", "")
Session = load_session (os.getenv ("BLEED_TEST_DIR"), os.getenv ("BLEED_TEST_NAME"))
if not Session then print ("ERROR load") return end
ARDOUR.LuaAPI.usleep (500000)        -- the controls' state (mute) is applied in the next process cycles
for r in Session:get_routes ():iter () do
	local t = r:to_track ()
	if not t:isnil () and t:playlist ():data_type ():to_string () == "audio" then
		local procs = {}
		local i = 0
		while true do
			local p = r:nth_plugin (i)
			if p:isnil () then break end
			procs[#procs + 1] = p:display_name ()
			i = i + 1
		end
		local outs = 0
		for c = 0, r:n_outputs ():n_audio () - 1 do
			if r:output ():audio (c):connected () then outs = outs + 1 end
		end
		print (string.format ("TRACK %s|%d|%d|%d|%.3f|%s|%d", r:name (), r:presentation_info_ptr ():order (),
			r:mute_control ():get_value (), r:n_inputs ():n_audio (), r:gain_control ():get_value (), table.concat (procs, ","), outs))
		for rg in t:playlist ():region_list ():iter () do
			local srcs = {}
			for c = 0, rg:to_audioregion ():n_channels () - 1 do
				srcs[#srcs + 1] = rg:source (c):name () .. "@" .. rg:source (c):natural_position ():samples ()
			end
			print (string.format ("REGION %s|%d|%d|%d|%s", r:name (), rg:position ():samples (), rg:length ():samples (),
				rg:to_audioregion ():n_channels (), table.concat (srcs, ",")))
		end
	end
end
print ("DONE")
Session:close ()
