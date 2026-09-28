file_path = '/app/src/services/exportador_service.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('part_0 = "   "', 'part_0 = "  "')
content = content.replace('part_8 = "   "', 'part_8 = "  "')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Updated spaces')
