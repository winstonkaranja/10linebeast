#!/usr/bin/env python3
"""
Test to understand PyMuPDF coordinate system behavior
"""

def explain_coordinate_systems():
    """Explain different PDF coordinate systems"""
    print("🔍 PDF COORDINATE SYSTEM ANALYSIS")
    print("=" * 40)
    print()
    
    print("📐 STANDARD PDF COORDINATES:")
    print("   • Origin (0,0) at BOTTOM-LEFT")
    print("   • Y increases going UP")
    print("   • Higher Y = closer to TOP")
    print("   • For 792pt page: Y=792 is TOP, Y=0 is BOTTOM")
    print()
    
    print("📐 PyMuPDF (fitz) COORDINATES:")
    print("   • Origin (0,0) at TOP-LEFT")
    print("   • Y increases going DOWN") 
    print("   • Higher Y = closer to BOTTOM")
    print("   • For 792pt page: Y=0 is TOP, Y=792 is BOTTOM")
    print()
    
    print("🎯 IMPLICATION FOR SORTING:")
    print("   If PyMuPDF uses top-left origin:")
    print("   • Line 1 (top of page) has Y ≈ 50")
    print("   • Line 2 (below line 1) has Y ≈ 75") 
    print("   • Line 3 (below line 2) has Y ≈ 100")
    print("   • ...")
    print("   • Bottom line has Y ≈ 750")
    print()
    print("   For TOP-TO-BOTTOM order, we need:")
    print("   • ASCENDING sort (lowest Y first)")
    print("   • NOT descending sort!")
    print()

def test_correct_sorting():
    """Test what the sorting should be with PyMuPDF coordinates"""
    print("🧪 TESTING CORRECT SORTING FOR PyMuPDF")
    print("=" * 45)
    
    # Simulate PyMuPDF coordinates (top-left origin)
    lines = [
        {'y': 50, 'text': 'Line 1 - TOP of page (smallest Y)'},
        {'y': 75, 'text': 'Line 2 - second from top'},
        {'y': 100, 'text': 'Line 3 - third from top'},
        {'y': 125, 'text': 'Line 4 - fourth from top'},
        {'y': 150, 'text': 'Line 5 - fifth from top'},
        {'y': 175, 'text': 'Line 6 - sixth from top'},
        {'y': 200, 'text': 'Line 7 - seventh from top'},
        {'y': 225, 'text': 'Line 8 - eighth from top'},
        {'y': 250, 'text': 'Line 9 - ninth from top'},
        {'y': 275, 'text': 'Line 10 - TENTH (should be numbered!)'},
        {'y': 300, 'text': 'Line 11 - eleventh from top'},
        {'y': 700, 'text': 'Line 12 - near BOTTOM of page (largest Y)'},
    ]
    
    print("PyMuPDF lines (unsorted):")
    for line in lines:
        print(f"   Y={line['y']:3.0f}: {line['text']}")
    
    print("\n🔄 CURRENT SORTING (reverse=True, descending Y):")
    sorted_desc = sorted(lines, key=lambda x: x['y'], reverse=True)
    for i, line in enumerate(sorted_desc, 1):
        marker = " ← 10TH!" if i == 10 else ""
        print(f"   {i:2d}. Y={line['y']:3.0f}: {line['text']}{marker}")
    
    print("\n🔄 CORRECT SORTING (ascending Y, lowest first):")
    sorted_asc = sorted(lines, key=lambda x: x['y'])
    for i, line in enumerate(sorted_asc, 1):
        marker = " ← 10TH!" if i == 10 else ""
        print(f"   {i:2d}. Y={line['y']:3.0f}: {line['text']}{marker}")
    
    print("\n📊 ANALYSIS:")
    if sorted_desc[9]['y'] == 700:  # 10th item with reverse=True
        print("❌ Current sorting puts BOTTOM line as 10th")
        print("❌ This explains bottom-to-top numbering behavior")
    
    if sorted_asc[9]['y'] == 275:  # 10th item with normal sort
        print("✅ Ascending sort puts correct line as 10th")
        print("✅ This would give proper top-to-bottom numbering")
    
    return sorted_asc

def main():
    explain_coordinate_systems()
    test_correct_sorting()
    
    print("\n🔧 SOLUTION:")
    print("=" * 20)
    print("Change the sorting line from:")
    print("   lines.sort(key=lambda x: x['y'], reverse=True)")
    print("To:")
    print("   lines.sort(key=lambda x: x['y'])  # Ascending order")
    print()
    print("This assumes PyMuPDF uses top-left origin coordinates")
    print("where Y=0 is top of page and Y increases downward.")

if __name__ == "__main__":
    main()