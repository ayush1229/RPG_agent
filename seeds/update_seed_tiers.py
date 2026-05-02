import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import json
import ast
import re

def calculate_tier(ability):
    if ability.get("ability_category") != "combat":
        return 0
    
    mana = ability.get("mana_cost", 0)
    has_effect = bool(ability.get("applies_status"))
    
    if mana >= 30:
        return 3
    if 15 <= mana < 30 and has_effect:
        return 2
    return 1

with open("seed.py", "r", encoding="utf-8") as f:
    content = f.read()

start_match = re.search(r"ABILITIES\s*:\s*list\[dict\]\s*=\s*\[", content)
if start_match:
    start_idx = start_match.start()
    end_idx = content.find("\n]", start_idx) + 2
    
    list_str = content[start_idx:end_idx]
    
    try:
        list_str_only = list_str.split("=", 1)[1].strip()
        abilities_list = eval(list_str_only)
        
        for ability in abilities_list:
            ability["tier"] = calculate_tier(ability)
            
        new_list_str = "ABILITIES: list[dict] = [\n"
        for a in abilities_list:
            new_list_str += f"  {repr(a)},\n"
        if new_list_str.endswith(",\n"):
            new_list_str = new_list_str[:-2] + "\n"
        new_list_str += "]"
        
        new_content = content[:start_idx] + new_list_str + content[end_idx:]
        
        with open("seed.py", "w", encoding="utf-8") as f:
            f.write(new_content)
        print("seed.py updated successfully.")
    except Exception as e:
        import traceback
        print("seed.py update failed:")
        traceback.print_exc()
else:
    print("Could not find ABILITIES in seed.py")
