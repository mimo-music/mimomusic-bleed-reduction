-- SPDX-License-Identifier: GPL-3.0-or-later
-- SPDX-FileCopyrightText: 2026 Mettronic GmbH

-- ardour_export_raw_setup.lua -- a test session for tools/export_raw_stems.sh
-- (run by tests/ardour_export_raw_test.sh):
--   "Mono": noise recorded, then everything that must NOT reach the stem: an amplifier
--           plugin (-20 dB), the fader at -20 dB, the track muted; and what must: the take
--           moved to 1 s, its region gain 0.5
--   "Stereo": noise on two channels, untouched
-- Saved and closed. Session folder in BLEED_TEST_DIR.
local function log (...) local t = {} for _, v in ipairs ({...}) do t[#t+1] = tostring (v) end io.stderr:write (table.concat (t, " ") .. "\n") end
local dir = os.getenv ("BLEED_TEST_DIR")
AudioEngine:set_backend ("None (Dummy)", "", "")
Session = create_session (dir, "rawtest", 48000)
local ok, err = pcall (function ()
	local gen = Session:new_audio_route (2, 2, ARDOUR.RouteGroup (), 1, "Gen", ARDOUR.PresentationInfo.Flag.AudioBus, ARDOUR.PresentationInfo.max_order):front ()
	gen:add_processor_by_index (ARDOUR.LuaAPI.new_luaproc (Session, "ACE Noise"), 0, nil, true)
	local m = Session:new_audio_track (1, 1, ARDOUR.RouteGroup (), 1, "Mono", ARDOUR.PresentationInfo.max_order, ARDOUR.TrackMode.Normal, true):front ()
	local s = Session:new_audio_track (2, 2, ARDOUR.RouteGroup (), 1, "Stereo", ARDOUR.PresentationInfo.max_order, ARDOUR.TrackMode.Normal, true):front ()
	for _, t in ipairs ({m, s}) do
		t:input ():disconnect_all (nil)
		for c = 0, t:n_inputs ():n_audio () - 1 do t:input ():audio (c):connect (gen:output ():audio (c):name ()) end
		t:rec_enable_control ():set_value (1, PBD.GroupControlDisposition.NoGroup)
	end
	ARDOUR.LuaAPI.usleep (500000)
	Session:maybe_enable_record (false)
	Session:request_roll (ARDOUR.TransportRequestSource.TRS_UI)
	ARDOUR.LuaAPI.usleep (4000000)
	Session:request_stop (false, false, ARDOUR.TransportRequestSource.TRS_UI)
	ARDOUR.LuaAPI.usleep (1500000)
	Session:disable_record (false, false)
	for _, t in ipairs ({m, s}) do t:rec_enable_control ():set_value (0, PBD.GroupControlDisposition.NoGroup) end
	-- processing that must not reach the stem
	local amp = ARDOUR.LuaAPI.new_luaproc (Session, "ACE Amplifier")
	m:add_processor_by_index (amp, 0, nil, true)
	ARDOUR.LuaAPI.set_processor_param (amp, 0, -20)
	m:gain_control ():set_value (0.1, PBD.GroupControlDisposition.NoGroup)
	m:mute_control ():set_value (1, PBD.GroupControlDisposition.NoGroup)
	-- the take's edit that must
	for r in m:playlist ():region_list ():iter () do
		r:set_position (Temporal.timepos_t (48000))
		r:to_audioregion ():set_scale_amplitude (0.5)
	end
	log ("range", Session:current_start_sample (), Session:current_end_sample ())
	Session:save_state ("", false, false, false, false, false)
end)
log ("setup", ok, err)
Session:close ()
