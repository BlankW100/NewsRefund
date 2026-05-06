import ctypes
import sys

from ui.app import NewsRefundApp


def main() -> None:
    # Save Windows console input mode so we can restore it after Textual exits
    # (Ctrl+C can leave the terminal in raw mode without this)
    _stdin_mode: int | None = None
    if sys.platform == "win32":
        _k32 = ctypes.windll.kernel32
        _handle = _k32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        _buf = ctypes.c_ulong()
        if _k32.GetConsoleMode(_handle, ctypes.byref(_buf)):
            _stdin_mode = _buf.value

    try:
        NewsRefundApp().run()
    except KeyboardInterrupt:
        pass
    finally:
        if sys.platform == "win32" and _stdin_mode is not None:
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-10), _stdin_mode
            )


if __name__ == "__main__":
    main()
