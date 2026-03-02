import json
import sys

files = {
    '2026-02-28-night (d4ec4cad)': r'C:\Users\User\AppData\Roaming\Code\User\workspaceStorage\429c25f7b123252d88226af750b60e33\GitHub.copilot-chat\transcripts\d4ec4cad-648a-42a0-ba51-0cf49c60161a.jsonl',
    '2026-03-01a-13h (d091fe42)': r'C:\Users\User\AppData\Roaming\Code\User\workspaceStorage\429c25f7b123252d88226af750b60e33\GitHub.copilot-chat\transcripts\d091fe42-695f-4348-ac36-aa2f25df6b1e.jsonl',
    '2026-03-01b-14h (1c834f0e)': r'C:\Users\User\AppData\Roaming\Code\User\workspaceStorage\429c25f7b123252d88226af750b60e33\GitHub.copilot-chat\transcripts\1c834f0e-cc63-4691-be0c-69c7eea73cb6.jsonl',
    '2026-03-01c-15h (b498464c)': r'C:\Users\User\AppData\Roaming\Code\User\workspaceStorage\429c25f7b123252d88226af750b60e33\GitHub.copilot-chat\transcripts\b498464c-2f4e-40d5-8335-5c7c7e480b0b.jsonl',
    '2026-02-26 (8e277499)': r'C:\Users\User\AppData\Roaming\Code\User\workspaceStorage\429c25f7b123252d88226af750b60e33\GitHub.copilot-chat\transcripts\8e277499-7077-4ad0-a5ee-88c41c6443b6.jsonl',
    '2026-02-27 (d90a90cb)': r'C:\Users\User\AppData\Roaming\Code\User\workspaceStorage\429c25f7b123252d88226af750b60e33\GitHub.copilot-chat\transcripts\d90a90cb-e4ff-42ef-bc03-f5a2ce08b773.jsonl',
}

out = open(r'C:\Users\User\source\repos\QIDIStudio\all_session_content.txt', 'w', encoding='utf-8')

for label, path in files.items():
    out.write(f'\n\n{"="*80}\n')
    out.write(f'SESSION: {label}\n')
    out.write(f'{"="*80}\n\n')
    
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    t = obj.get('type', '')
                    data = obj.get('data', {})
                    ts = obj.get('timestamp', '')[:19]
                    
                    if t == 'user.message':
                        content = data.get('content', '')
                        if content:
                            out.write(f'[{ts}] USER: {content[:500]}\n\n')
                    
                    elif t == 'assistant.message':
                        # assistant message content may be in different places
                        content = data.get('content', '')
                        if not content:
                            # try parts
                            parts = data.get('parts', [])
                            for p in parts:
                                if isinstance(p, dict) and p.get('type') == 'text':
                                    content += p.get('text', '')
                        if content:
                            out.write(f'[{ts}] ASST: {str(content)[:800]}\n\n')
                    
                    elif t == 'tool.call':
                        tool_name = data.get('name', data.get('toolName', ''))
                        out.write(f'[{ts}] TOOL: {tool_name}\n')
                    
                    elif t == 'tool.result':
                        pass  # skip results to keep output manageable
                        
                except Exception as e:
                    pass
    except Exception as e:
        out.write(f'ERROR reading {path}: {e}\n')

out.close()
print("Done")
