"""
統合テスト - UIと全機能の動作確認（短時間版）
"""
import sys
import tkinter as tk
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from zoom_auto_capture.ui import ZoomRecorderProgram
from zoom_auto_capture import config


def test_ui_integration():
    """Test UI with all features for a short duration."""
    print("=" * 60)
    print("UI統合テスト（5秒間）")
    print("=" * 60)
    print("このテストは UI を起動し、5秒後に自動的に終了します。")
    print("Zoom が起動していれば録音・スクリーンショットが開始されます。")
    print("=" * 60)
    
    config.ensure_directories()
    
    root = tk.Tk()
    app = ZoomRecorderProgram(root)
    
    # Schedule auto-close after 5 seconds
    def auto_close():
        print("\n自動終了します...")
        app.on_quit()
    
    root.after(5000, auto_close)
    
    print("\nUI を起動しました。5秒後に自動終了します...")
    root.mainloop()
    
    print("\n✓ UI が正常に終了しました。")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        success = test_ui_integration()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nテストが中断されました。")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ テスト中にエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
