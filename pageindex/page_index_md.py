import asyncio
import json
import re
import tiktoken

def count_tokens(text, model):
    enc = tiktoken.encoding_for_model(model)
    tokens = enc.encode(text)
    return len(tokens)


def extract_nodes_from_markdown(markdown_content):
    header_pattern = r'^(#{1,6})\s+(.+)$'
    node_list = []
    
    lines = markdown_content.split('\n')
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
            
        match = re.match(header_pattern, line)
        if match:
            title = match.group(2).strip()
            node_list.append({'node_title': title, 'line_num': line_num})

    return node_list,lines


def extract_node_text_content(node_list, markdown_lines, model="gpt-4o"):    
    all_nodes = []
    for node in node_list:
        processed_node = {
            'title': node['node_title'],
            'line_num': node['line_num'],
            'level': len(re.match(r'^(#{1,6})', markdown_lines[node['line_num'] - 1]).group(1))
        }
        all_nodes.append(processed_node)
    
    for i, node in enumerate(all_nodes):
        start_line = node['line_num'] - 1 
        if i + 1 < len(all_nodes):
            end_line = all_nodes[i + 1]['line_num'] - 1 
        else:
            end_line = len(markdown_lines)
        
        node['text'] = '\n'.join(markdown_lines[start_line:end_line]).strip()
        node['text_token_count'] = count_tokens(node['text'], model)
    
    return all_nodes


def tree_thinning_for_index(node_list, min_node_token=None):
    def find_all_children(parent_index, parent_level, node_list):
        children_indices = []
        
        for i in range(parent_index + 1, len(node_list)):
            current_level = node_list[i]['level']
            
            if current_level <= parent_level:
                break
                
            children_indices.append(i)
        
        return children_indices
    
    result_list = node_list.copy()
    nodes_to_remove = set()
    
    for i in range(len(result_list) - 1, -1, -1):
        if i in nodes_to_remove:
            continue
            
        current_node = result_list[i]
        current_level = current_node['level']
        
        total_tokens = current_node.get('text_token_count', 0)
        
        if total_tokens < min_node_token:
            children_indices = find_all_children(i, current_level, result_list)
            
            children_texts = []
            for child_index in sorted(children_indices):
                if child_index not in nodes_to_remove:
                    child_text = result_list[child_index].get('text', '')
                    if child_text.strip():
                        children_texts.append(child_text)
                    nodes_to_remove.add(child_index)
            
            if children_texts:
                parent_text = current_node.get('text', '')
                merged_text = parent_text
                for child_text in children_texts:
                    if merged_text and not merged_text.endswith('\n'):
                        merged_text += '\n\n'
                    merged_text += child_text
                
                result_list[i]['text'] = merged_text
                
                result_list[i]['text_token_count'] = count_tokens(merged_text, "gpt-4o")
    
    for index in sorted(nodes_to_remove, reverse=True):
        result_list.pop(index)
    
    return result_list


def build_tree_from_nodes(node_list):
    if not node_list:
        return []
    
    stack = []
    root_nodes = []
    node_counter = 1
    
    for node in node_list:
        current_level = node['level']
        
        tree_node = {
            'title': node['title'],
            'node_id': str(node_counter).zfill(4),
            'text': node['text'],
            'line_num': node['line_num'],
            'nodes': []
        }
        node_counter += 1
        
        while stack and stack[-1][1] >= current_level:
            stack.pop()
        
        if not stack:
            root_nodes.append(tree_node)
        else:
            parent_node, parent_level = stack[-1]
            parent_node['nodes'].append(tree_node)
        
        stack.append((tree_node, current_level))
    
    return root_nodes


def clean_tree_for_output(tree_nodes):
    cleaned_nodes = []
    
    for node in tree_nodes:
        cleaned_node = {
            'title': node['title'],
            'node_id': node['node_id'],
            'text': node['text'],
            'line_num': node['line_num']
        }
        
        if node['nodes']:
            cleaned_node['nodes'] = clean_tree_for_output(node['nodes'])
        
        cleaned_nodes.append(cleaned_node)
    
    return cleaned_nodes

def md_to_tree(md_path, if_thinning=True, min_token_threshold=None):
    with open(md_path, 'r', encoding='utf-8') as f:
        markdown_content = f.read()
    
    node_list, markdown_lines = extract_nodes_from_markdown(markdown_content)
    nodes_with_content = extract_node_text_content(node_list, markdown_lines)
    
    if if_thinning:
        thinned_nodes = tree_thinning_for_index(nodes_with_content, min_token_threshold)
    else:
        thinned_nodes = nodes_with_content
    
    tree_structure = build_tree_from_nodes(thinned_nodes)
    return tree_structure


if __name__ == "__main__":
    import os
    import json
    
    # Path to the Welcome.md file
    md_path = os.path.join(os.path.dirname(__file__), '..', 'docs', 'Welcome.md')
    

    tree_structure = md_to_tree(md_path, if_thinning=True, min_token_threshold=100)

    def print_tree(nodes, indent=0):
        for node in nodes:
            prefix = "  " * indent
            has_children = 'nodes' in node and node['nodes']
            children_info = f" ({len(node['nodes'])} children)" if has_children else ""
            print(f"{prefix}- {node['title']} [ID: {node['node_id']}]{children_info}")
            if has_children:
                print_tree(node['nodes'], indent + 1)
    
    print("\n🌳 Tree Structure:")
    print_tree(tree_structure)
    
    output_path = os.path.join(os.path.dirname(__file__), '..', 'results', 'Welcome_structure.json')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(tree_structure, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Tree structure saved to: {output_path}")