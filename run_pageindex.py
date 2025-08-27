import argparse
import os
import json
from pageindex import *
from pageindex.page_index_md import md_to_tree

if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Process PDF or Markdown document and generate structure')
    parser.add_argument('--file_path', type=str, help='Path to the PDF or Markdown file')
    parser.add_argument('--file_type', type=str, choices=['pdf', 'markdown', 'md'], default='pdf',
                      help='Type of file to process (pdf, markdown, or md)')
    parser.add_argument('--model', type=str, default='gpt-4o-2024-11-20', help='Model to use')
    parser.add_argument('--toc-check-pages', type=int, default=20, 
                      help='Number of pages to check for table of contents (PDF only)')
    parser.add_argument('--max-pages-per-node', type=int, default=10,
                      help='Maximum number of pages per node (PDF only)')
    parser.add_argument('--max-tokens-per-node', type=int, default=20000,
                      help='Maximum number of tokens per node (PDF only)')
    parser.add_argument('--if-add-node-id', type=str, default='yes',
                      help='Whether to add node id to the node')
    parser.add_argument('--if-add-node-summary', type=str, default='no',
                      help='Whether to add summary to the node')
    parser.add_argument('--if-add-doc-description', type=str, default='yes',
                      help='Whether to add doc description to the doc')
    parser.add_argument('--if-add-node-text', type=str, default='no',
                      help='Whether to add text to the node')
    # Markdown specific arguments
    parser.add_argument('--if-thinning', type=str, default='yes',
                      help='Whether to apply tree thinning for markdown (markdown only)')
    parser.add_argument('--thinning-threshold', type=int, default=5000,
                      help='Minimum token threshold for thinning (markdown only)')
    parser.add_argument('--summary-token-threshold', type=int, default=200,
                      help='Token threshold for generating summaries (markdown only)')
    args = parser.parse_args()
    
    # Determine file type from extension if not specified
    if args.file_type == 'pdf' and args.file_path:
        if args.file_path.lower().endswith(('.md', '.markdown')):
            args.file_type = 'markdown'
        elif not args.file_path.lower().endswith('.pdf'):
            raise ValueError("File must be a PDF or Markdown file")
    
    if args.file_type == 'pdf':
        # Process PDF file
        # Configure options
        opt = config(
            model=args.model,
            toc_check_page_num=args.toc_check_pages,
            max_page_num_each_node=args.max_pages_per_node,
            max_token_num_each_node=args.max_tokens_per_node,
            if_add_node_id=args.if_add_node_id,
            if_add_node_summary=args.if_add_node_summary,
            if_add_doc_description=args.if_add_doc_description,
            if_add_node_text=args.if_add_node_text
        )

        # Process the PDF
        toc_with_page_number = page_index_main(args.file_path, opt)
        print('Parsing done, saving to file...')
        
        # Save results
        pdf_name = os.path.splitext(os.path.basename(args.file_path))[0]    
        os.makedirs('./results', exist_ok=True)
        
        with open(f'./results/{pdf_name}_structure.json', 'w', encoding='utf-8') as f:
            json.dump(toc_with_page_number, f, indent=2)
            
    elif args.file_type in ['markdown', 'md']:
        # Process markdown file
        print('Processing markdown file...')
        
        # Configure markdown options
        if_thinning = args.if_thinning.lower() == 'yes'
        if_summary = args.if_add_node_summary.lower() == 'yes'
        
        # Process the markdown
        import asyncio
        toc_with_page_number = asyncio.run(md_to_tree(
            md_path=args.file_path,
            if_thinning=if_thinning,
            min_token_threshold=args.thinning_threshold,
            if_summary=if_summary,
            summary_token_threshold=args.summary_token_threshold,
            model=args.model
        ))
        
        print('Parsing done, saving to file...')
        
        # Save results
        md_name = os.path.splitext(os.path.basename(args.file_path))[0]    
        os.makedirs('./results', exist_ok=True)
        
        with open(f'./results/{md_name}_structure.json', 'w', encoding='utf-8') as f:
            json.dump(toc_with_page_number, f, indent=2, ensure_ascii=False)
    else:
        raise ValueError(f"Unsupported file type: {args.file_type}. Supported types are 'pdf', 'markdown', or 'md'")