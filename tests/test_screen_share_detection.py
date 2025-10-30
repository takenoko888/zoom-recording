"""
Test screen share window detection functionality.
"""
import time
import logging
from pathlib import Path

# Add parent directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from zoom_auto_capture import process_utils
from zoom_auto_capture.screenshot import ScreenshotCapture
from zoom_auto_capture import config

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_screen_share_detection():
    """Test if screen share window can be detected."""
    print("\n=== 画面共有ウィンドウ検出テスト ===")
    print("Zoomで画面共有を開始してください...")
    print("15秒間、画面共有ウィンドウの検出を試みます。\n")
    
    found_share_window = False
    
    for i in range(15):
        print(f"[{i+1}/15] チェック中...", end=" ")
        
        # Check if Zoom is running
        if not process_utils.is_zoom_running():
            print("Zoom未起動")
            time.sleep(1)
            continue
        
        # Try to find screen share window
        share_window = process_utils.get_zoom_screen_share_window()
        
        if share_window:
            hwnd, title = share_window
            print(f"✅ 画面共有ウィンドウ検出!")
            print(f"   ウィンドウタイトル: {title}")
            print(f"   ウィンドウハンドル: {hwnd}")
            found_share_window = True
            
            # Get window dimensions
            try:
                import win32gui
                rect = win32gui.GetWindowRect(hwnd)
                left, top, right, bottom = rect
                width = right - left
                height = bottom - top
                print(f"   ウィンドウサイズ: {width}x{height}px")
                print(f"   位置: ({left}, {top})")
            except Exception as e:
                print(f"   サイズ取得エラー: {e}")
        else:
            print("画面共有なし")
        
        time.sleep(1)
    
    print("\n=== テスト結果 ===")
    if found_share_window:
        print("✅ 画面共有ウィンドウの検出に成功しました!")
    else:
        print("❌ 画面共有ウィンドウが検出されませんでした。")
        print("   Zoomで画面共有を開始していることを確認してください。")

def test_screenshot_with_screen_share():
    """Test screenshot capture with screen share window."""
    print("\n=== 画面共有スクリーンショットテスト ===")
    print("このテストは10秒間実行されます。")
    print("Zoomで画面共有を開始してください。\n")
    
    capture = ScreenshotCapture()
    
    if not capture.is_available:
        print("❌ mss/Pillowが利用できません。")
        return
    
    # Start capture
    meeting_title = "画面共有テスト"
    meeting_slug = "screen_share_test"
    
    print("スクリーンショット取得を開始...")
    capture.start(meeting_title, meeting_slug)
    
    # Wait and show status
    for i in range(10):
        time.sleep(1)
        count = capture.screenshot_count
        print(f"[{i+1}/10秒] スクリーンショット数: {count}")
        
        # Check if screen share window exists
        share_window = process_utils.get_zoom_screen_share_window()
        if share_window:
            _, title = share_window
            print(f"         画面共有中: {title}")
    
    # Stop capture
    capture.stop()
    
    final_count = capture.screenshot_count
    print(f"\n=== テスト完了 ===")
    print(f"保存されたスクリーンショット: {final_count}枚")
    
    if capture.last_screenshot_path:
        print(f"最後のスクリーンショット: {capture.last_screenshot_path}")

if __name__ == "__main__":
    print("=" * 60)
    print("画面共有検出・キャプチャテスト")
    print("=" * 60)
    
    # Test 1: Detection only
    test_screen_share_detection()
    
    print("\n" + "=" * 60)
    input("次のテストに進むにはEnterを押してください...")
    
    # Test 2: Screenshot with screen share
    test_screenshot_with_screen_share()
    
    print("\n" + "=" * 60)
    print("すべてのテストが完了しました!")
    print("=" * 60)
