import os
import re
import json
import glob

brain_dir = r'C:\Users\gchet\.gemini\antigravity\brain'
out_dir = r'c:\Users\gchet\OneDrive\Desktop\antigravi\templates'

for log_path in glob.glob(os.path.join(brain_dir, '*', '.system_generated', 'logs', 'overview.txt')):
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            text = f.read()
    except:
        continue

    # Regex to find TargetFile and CodeContent in the write_to_file tool calls
    matches = re.finditer(r'\"name\":\"write_to_file\",\"args\":\{.*?(?:\"TargetFile\":\"(.*?)\".*?\"CodeContent\":\"(.*?)\"|\"CodeContent\":\"(.*?)\".*?\"TargetFile\":\"(.*?)\").*?\}', text)
    for m in matches:
        if m.group(1) and m.group(2):
            target = m.group(1).replace('\\\\', '\\')
            code = m.group(2)
        elif m.group(3) and m.group(4):
            code = m.group(3)
            target = m.group(4).replace('\\\\', '\\')
        else:
            continue
        
        if 'templates' in target and target.endswith('.html'):
            filename = os.path.basename(target)
            try:
                # Load the JSON string into actual string to handle newlines
                content = json.loads('\"' + code + '\"')
                content = content.replace('SoilIQ', 'AgriSense').replace('soiliq', 'agrisense')
                
                out_path = os.path.join(out_dir, filename)
                with open(out_path, 'w', encoding='utf-8') as out:
                    out.write(content)
                print(f'Restored {filename}')
            except Exception as e:
                pass
