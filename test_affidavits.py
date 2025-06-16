#!/usr/bin/env python3
"""
Test script to merge affidavit1.pdf and Affidavit2.pdf with repagination and tenth lining
"""

import base64
import json
from legal_processor import StatelessLegalProcessor

def encode_pdf_to_base64(filepath):
    """Read PDF file and encode to base64"""
    try:
        with open(filepath, 'rb') as pdf_file:
            pdf_content = pdf_file.read()
            return base64.b64encode(pdf_content).decode('utf-8')
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None

def main():
    print("🔧 Testing Affidavit Processing: Merge + Repaginate + Tenth Line")
    print("=" * 60)
    
    # Read and encode the PDF files
    print("📖 Reading affidavit files...")
    
    affidavit1_content = encode_pdf_to_base64('affidavit1.pdf')
    affidavit2_content = encode_pdf_to_base64('Affidavit2.pdf')
    
    if not affidavit1_content:
        print("❌ Could not read affidavit1.pdf")
        return False
    
    if not affidavit2_content:
        print("❌ Could not read Affidavit2.pdf")
        return False
    
    print("✅ Both affidavit files read successfully")
    
    # Create the event for processing
    event = {
        "documents": [
            {
                "filename": "affidavit1.pdf",
                "content": affidavit1_content,
                "order": 1  # This will be first
            },
            {
                "filename": "Affidavit2.pdf", 
                "content": affidavit2_content,
                "order": 2  # This will be second
            }
        ],
        "features": {
            "merge_pdfs": True,      # Combine both PDFs
            "repaginate": True,      # Add page numbers
            "tenth_lining": True     # Add line numbers every 10th line
        }
    }
    
    # Process the documents
    print("\n⚙️ Processing documents...")
    print("   - Merging affidavit1.pdf and Affidavit2.pdf")
    print("   - Adding page numbers (repagination)")
    print("   - Adding 10th line numbering")
    
    try:
        processor = StatelessLegalProcessor()
        result = processor.lambda_handler(event, None)
        
        print(f"\n📊 Status Code: {result['statusCode']}")
        
        if result['statusCode'] == 200:
            body = json.loads(result['body'])
            
            if body['success']:
                processed_doc = body['processed_document']
                
                print("✅ Processing successful!")
                print(f"📁 Output filename: {processed_doc['filename']}")
                print(f"📄 Total pages: {processed_doc['pages']}")
                print(f"🛠️ Features applied: {processed_doc['features_applied']}")
                print(f"⏱️ Processing time: {processed_doc['processing_time_seconds']} seconds")
                print(f"💾 From cache: {processed_doc.get('from_cache', False)}")
                
                # Save the result as compiled_document.pdf
                print(f"\n💾 Saving result as compiled_document.pdf...")
                
                try:
                    output_pdf_bytes = base64.b64decode(processed_doc['content'])
                    with open('compiled_document.pdf', 'wb') as f:
                        f.write(output_pdf_bytes)
                    
                    print("✅ Successfully saved compiled_document.pdf")
                    print("📖 Open compiled_document.pdf to view the merged, repaginated, and tenth-lined document!")
                    
                    return True
                    
                except Exception as e:
                    print(f"❌ Error saving compiled_document.pdf: {e}")
                    return False
            else:
                print(f"❌ Processing failed: {body.get('error')}")
                return False
        else:
            body = json.loads(result['body'])
            print(f"❌ Request failed: {body.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error during processing: {e}")
        return False

if __name__ == "__main__":
    success = main()
    
    if success:
        print(f"\n🎉 SUCCESS! Check compiled_document.pdf to see:")
        print("   1. Both affidavits merged into one document")  
        print("   2. Continuous page numbering across both documents")
        print("   3. Line numbers every 10th line")
        print("\n📁 The file 'compiled_document.pdf' is ready to open!")
    else:
        print(f"\n❌ Test failed - check the error messages above")