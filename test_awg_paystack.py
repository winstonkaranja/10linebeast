#!/usr/bin/env python3
"""
Test script to merge AWG and Paystack PDFs with repagination and tenth lining
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
    print("🔧 Testing AWG + Paystack PDF Processing: Merge + Repaginate + Tenth Line")
    print("=" * 70)
    
    # Define the file paths
    awg_file = "AWG  another v Rsm Eastern Africa LLP  another (Cause E439E428of2020 (Consolidated)) 2025KEELRC1336(KLR) (9May2025) (Judgment).pdf"
    paystack_file = "Paystack_Merchant_Service_Agreement_1479543 (1).pdf"
    
    # Read and encode the PDF files
    print("📖 Reading PDF files...")
    print(f"   - AWG file: {awg_file[:50]}...")
    print(f"   - Paystack file: {paystack_file}")
    
    awg_content = encode_pdf_to_base64(awg_file)
    paystack_content = encode_pdf_to_base64(paystack_file)
    
    if not awg_content:
        print(f"❌ Could not read AWG file")
        return False
    
    if not paystack_content:
        print(f"❌ Could not read Paystack file")
        return False
    
    print("✅ Both PDF files read successfully")
    
    # Create the event for processing
    event = {
        "documents": [
            {
                "filename": "awg_judgment.pdf",
                "content": awg_content,
                "order": 1  # AWG judgment first
            },
            {
                "filename": "paystack_agreement.pdf", 
                "content": paystack_content,
                "order": 2  # Paystack agreement second
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
    print("   - Merging AWG judgment and Paystack agreement")
    print("   - Adding continuous page numbering")
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
                
                # Save the result as compiled_awg_paystack.pdf
                output_filename = 'compiled_awg_paystack.pdf'
                print(f"\n💾 Saving result as {output_filename}...")
                
                try:
                    output_pdf_bytes = base64.b64decode(processed_doc['content'])
                    with open(output_filename, 'wb') as f:
                        f.write(output_pdf_bytes)
                    
                    print(f"✅ Successfully saved {output_filename}")
                    print(f"📖 Open {output_filename} to view the merged, repaginated, and tenth-lined document!")
                    
                    return True
                    
                except Exception as e:
                    print(f"❌ Error saving {output_filename}: {e}")
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
        print(f"\n🎉 SUCCESS! Check compiled_awg_paystack.pdf to see:")
        print("   1. AWG judgment + Paystack agreement merged into one document")  
        print("   2. Continuous page numbering across both documents")
        print("   3. Line numbers every 10th line for legal reference")
        print("\n📁 The file 'compiled_awg_paystack.pdf' is ready to open!")
    else:
        print(f"\n❌ Test failed - check the error messages above")