"""
簡易的な統合テスト - スクリーンショット機能の動作確認
"""
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from zoom_auto_capture.screenshot import ScreenshotCapture
from zoom_auto_capture import config


def test_screenshot_capture():
    """Test screenshot capture functionality."""
    print("=" * 60)
    print("スクリーンショット機能テスト")
    print("=" * 60)

    capture = ScreenshotCapture()

    # Check availability
    if not capture.is_available:
        print("❌ mss / Pillow が見つかりません。依存関係をインストールしてください。")
        return False

    print("✓ mss / Pillow が利用可能です。")

    # Start capture
    print("\n1. スクリーンショット取得を開始します...")
    capture.start("テスト会議", "test_meeting")
    
    if not capture.is_running:
        print("❌ スクリーンショット取得の開始に失敗しました。")
        return False
    
    print("✓ スクリーンショット取得を開始しました。")
    
    # Wait and capture some screenshots
    print("\n2. 10秒間画面を監視します。ウィンドウを切り替えるとスクリーンショットが撮影されます...")
    for i in range(10):
        time.sleep(1)
        status = capture.status
        print(f"   {i+1}秒経過 - スクリーンショット枚数: {status.screenshot_count}")
    
    # Stop capture
    print("\n3. スクリーンショット取得を停止します...")
    capture.stop()
    
    if capture.is_running:
        print("❌ スクリーンショット取得の停止に失敗しました。")
        return False
    
    final_status = capture.status
    print(f"✓ スクリーンショット取得を停止しました。")
    print(f"  合計枚数: {final_status.screenshot_count}")
    
    if final_status.last_screenshot_path:
        print(f"  最終ファイル: {final_status.last_screenshot_path}")
        if final_status.last_screenshot_path.exists():
            print(f"  ✓ ファイルが存在します。")
        else:
            print(f"  ❌ ファイルが見つかりません。")
            return False
    
    # Check output directory
    today = time.strftime("%Y%m%d")
    output_dir = config.SCREENSHOT_DIR / today / "test_meeting"
    
    if output_dir.exists():
        files = list(output_dir.glob("*.png"))
        print(f"\n4. 出力ディレクトリ確認:")
        print(f"   パス: {output_dir}")
        print(f"   ファイル数: {len(files)}")
        
        if len(files) != final_status.screenshot_count:
            print(f"   ⚠️ ファイル数が一致しません（期待: {final_status.screenshot_count}, 実際: {len(files)}）")
        else:
            print(f"   ✓ ファイル数が一致します。")
    else:
        print(f"\n4. ❌ 出力ディレクトリが見つかりません: {output_dir}")
        return False
    
    print("\n" + "=" * 60)
    print("✓ すべてのテストが正常に完了しました。")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        success = test_screenshot_capture()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nテストが中断されました。")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ テスト中にエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
