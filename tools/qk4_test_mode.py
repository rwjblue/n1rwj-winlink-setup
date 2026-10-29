"""Read the radio-reported TX TEST indicator from QK4 Vail's macOS UI."""

import subprocess


def require_radio_test_mode():
    # QK4 does not return TS GET on its CAT server. Its VFO TEST indicator is
    # driven by radio TS replies. Ignore the permanent TEST caption underneath
    # the XMIT button in SideControlPanel; it says nothing about radio state.
    script = """
tell application "System Events"
  set appProcess to first process whose bundle identifier is "com.rwjblue.qk4.vail"
  repeat with t in static texts of window "QK4" of appProcess
    try
      if value of t is "TEST" then
        set ident to value of attribute "AXIdentifier" of t
        if ident contains ".VfoRowWidget." then return "true"
      end if
    end try
  end repeat
  return "false"
end tell
"""
    result = subprocess.check_output(
        ["osascript", "-"], input=script, text=True, timeout=10
    )
    if result.strip() != "true":
        raise RuntimeError(
            "K4 TX TEST is not confirmed by QK4's VFO indicator; no keying allowed"
        )
