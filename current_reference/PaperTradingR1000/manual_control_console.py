# manual_control_console.py
# Compatibility wrapper over the canonical Manual Trading Core.

import manual_trading_core as _core

globals().update(
    {name: value for name, value in vars(_core).items() if not name.startswith("__")}
)

if __name__ == "__main__":
    raise SystemExit(_core.run_console())
