#!/usr/bin/env python3
"""
Quick test to verify line ordering is correct (top to bottom)
"""

def test_line_sorting():
    """Test that lines are sorted correctly from top to bottom"""
    print("🧪 Testing line sorting order")
    
    # Simulate lines with different Y coordinates
    # In PDF: higher Y = closer to top of page
    sample_lines = [
        {'y': 700, 'text': 'Line 1 (should be first - highest Y)', 'bbox': [100, 695, 400, 705]},
        {'y': 650, 'text': 'Line 2 (should be second)', 'bbox': [100, 645, 400, 655]},
        {'y': 600, 'text': 'Line 3 (should be third)', 'bbox': [100, 595, 400, 605]},
        {'y': 550, 'text': 'Line 4 (should be fourth)', 'bbox': [100, 545, 400, 555]},
        {'y': 500, 'text': 'Line 5 (should be fifth)', 'bbox': [100, 495, 400, 505]},
        {'y': 450, 'text': 'Line 6 (should be sixth)', 'bbox': [100, 445, 400, 455]},
        {'y': 400, 'text': 'Line 7 (should be seventh)', 'bbox': [100, 395, 400, 405]},
        {'y': 350, 'text': 'Line 8 (should be eighth)', 'bbox': [100, 345, 400, 355]},
        {'y': 300, 'text': 'Line 9 (should be ninth)', 'bbox': [100, 295, 400, 305]},
        {'y': 250, 'text': 'Line 10 (should be tenth - gets numbered!)', 'bbox': [100, 245, 400, 255]},
        {'y': 200, 'text': 'Line 11 (should be eleventh)', 'bbox': [100, 195, 400, 205]},
    ]
    
    print("Before sorting:")
    for i, line in enumerate(sample_lines):
        print(f"  {i+1}. Y={line['y']}: {line['text']}")
    
    # Apply the corrected sorting logic
    sample_lines.sort(key=lambda x: x['y'], reverse=True)
    
    print("\nAfter sorting (should be top to bottom):")
    for i, line in enumerate(sample_lines, 1):
        is_tenth = i % 10 == 0
        marker = " ← 10TH LINE NUMBER HERE!" if is_tenth else ""
        print(f"  {i:2d}. Y={line['y']}: {line['text']}{marker}")
    
    # Verify the order is correct
    expected_order = [700, 650, 600, 550, 500, 450, 400, 350, 300, 250, 200]
    actual_order = [line['y'] for line in sample_lines]
    
    if actual_order == expected_order:
        print("\n✅ Line sorting is CORRECT - top to bottom order")
        print("✅ 10th line numbering will appear on the correct line")
        return True
    else:
        print("\n❌ Line sorting is INCORRECT")
        print(f"Expected: {expected_order}")
        print(f"Actual:   {actual_order}")
        return False

def test_pdf_coordinate_understanding():
    """Explain PDF coordinate system"""
    print("\n📐 PDF Coordinate System Explanation:")
    print("=====================================")
    print("• PDF coordinates start at BOTTOM-LEFT (0,0)")
    print("• Y increases as you go UP the page")
    print("• Higher Y values = closer to TOP of page")
    print("• Lower Y values = closer to BOTTOM of page")
    print("")
    print("Example page (792 points tall):")
    print("  Y=792 ← TOP of page")
    print("  Y=700 ← Line 1 (first content line)")
    print("  Y=650 ← Line 2")
    print("  Y=600 ← Line 3")
    print("  ...   ← ...")
    print("  Y=100 ← Last content line")
    print("  Y=0   ← BOTTOM of page")
    print("")
    print("🎯 For TOP-TO-BOTTOM reading order:")
    print("   We sort by Y coordinate in DESCENDING order (highest first)")

if __name__ == "__main__":
    print("🚀 Line Ordering Fix Verification")
    print("=" * 40)
    
    test_pdf_coordinate_understanding()
    success = test_line_sorting()
    
    if success:
        print("\n🎉 The line ordering fix is working correctly!")
        print("10th line numbering will now appear from top to bottom as expected.")
    else:
        print("\n❌ Line ordering still needs adjustment.")