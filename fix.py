import re
fn = 'src/engine/graph_builder.py'
with open(fn, 'r', encoding='utf-8') as f:
    text = f.read()

start = text.find('_HTML_TEMPLATE = """\\')
end = text.find('"""', start + 20)
template = text[start:end]

format_vars = ['vis_cdn', 'nodes_json', 'edges_json', 'meta_json', 'layer_labels_json', 'layer_colors_json', 'highlight_node_json', 'vis_local']

# First convert all { to {{ and } to }}
new_template = template.replace('{', '{{').replace('}', '}}')
# Then replace {{{{var}}}} back to {var}
for var in format_vars:
    new_template = new_template.replace(f'{{{{{var}}}}}', f'{{{var}}}')

# Wait, if there were already some double braces from lines that didn't get changed, they will become quadruple braces.
# We should probably just do a regex substitution: any brace not enclosing a format var becomes double.
# Since python format allows {{ to escape {, we can just un-double all first, then double all, then format var.
new_template = template.replace('{{', '{').replace('}}', '}') # normalize to single
new_template = new_template.replace('{', '{{').replace('}', '}}') # double everything
for var in format_vars:
    new_template = new_template.replace(f'{{{{{var}}}}}', f'{{{var}}}')

text = text[:start] + new_template + text[end:]
with open(fn, 'w', encoding='utf-8') as f:
    f.write(text)
print('Fixed HTML template braces.')
