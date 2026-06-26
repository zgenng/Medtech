import re
import pandas as pd
from typing import List, Dict, Union, Optional

def clean_price(val: Union[str, float, int, None]) -> float:
    if pd.isna(val):
        return 0.0
    s = str(val).strip()
    if not s:
        return 0.0
    s = re.sub(r'\s+', '', s)
    if ',' in s and '.' in s:
        s = s.replace(',', '')
    elif ',' in s:
        if s.count(',') > 1:
            s = s.replace(',', '')
        else:
            if re.search(r',(\d{3})$', s):
                s = s.replace(',', '')
            else:
                s = s.replace(',', '.')
    s = re.sub(r'[^\d.]', '', s)
    if not s:
        return 0.0
    if s.count('.') > 1:
        parts = s.split('.')
        s = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(s)
    except ValueError:
        return 0.0

def clean_string(val: Union[str, float, int, None]) -> str:
    if pd.isna(val):
        return ""
    s = str(val).strip()
    s = re.sub(r'\s+', ' ', s)
    return s

def normalize_cell_val(val: Union[str, float, int, None]) -> str:
    if pd.isna(val):
        return ""
    if isinstance(val, float) and val.is_integer():
        val = int(val)
    s = str(val).strip()
    if s.endswith('.0'):
        s = s[:-2]
    return s

def parse_csv_excel(file_path: str) -> List[Dict[str, Union[str, float, None]]]:
    try:
        df = pd.read_excel(file_path, header=None, engine='openpyxl')
        print(f"✅ Файл ашылды: {file_path}")
    except Exception as e:
        print(f"❌ Қате: {e}")
        return []
    
    strategy = None
    header_row_idx = None
    code_col = name_col = res_col = sng_col = nonres_col = None
    num_rows = df.shape[0]
    
    # СТРАТЕГИЯ 1: 1,2,3,4,5,6,7,8 сандары бар жол
    for i in range(num_rows):
        row_vals = df.iloc[i].tolist()
        normalized_row = [normalize_cell_val(x) for x in row_vals]
        normalized_set = set(normalized_row)
        
        if {'1','2','3','4','5','6','7','8'}.issubset(normalized_set):
            strategy = 1
            header_row_idx = i
            print(f"✅ Стратегия 1: жол {i} табылды")
            
            for idx, val in enumerate(normalized_row):
                if val == '2':
                    code_col = idx
                elif val == '3':
                    name_col = idx
                elif val == '6':
                    res_col = idx
                elif val == '7':
                    sng_col = idx
                elif val == '8':
                    nonres_col = idx
            break
    
    # СТРАТЕГИЯ 2: Мәтін арқылы іздеу
    if strategy is None:
        for i in range(num_rows):
            row_vals = df.iloc[i].tolist()
            row_clean = [str(x).lower() if not pd.isna(x) else "" for x in row_vals]
            
            has_name = any("наименование" in x or "услуга" in x for x in row_clean)
            has_price = any("цена" in x or "стоимость" in x for x in row_clean)
            
            if has_name and has_price:
                strategy = 2
                header_row_idx = i
                print(f"✅ Стратегия 2: жол {i} табылды")
                
                for idx, val_str in enumerate(row_clean):
                    if "снг" in val_str or "ближнего зарубежья" in val_str:
                        sng_col = idx
                    elif "дальнего зарубежья" in val_str or "нерезидент" in val_str:
                        nonres_col = idx
                    elif "код" in val_str and "тарификатор" in val_str:
                        code_col = idx
                    elif "для граждан республики казахстан" in val_str or "цена" in val_str:
                        res_col = idx
                    elif "наименование" in val_str or "услуга" in val_str:
                        name_col = idx
                break
    
    if strategy is None:
        print("❌ Ешқандай стратегия табылмады!")
        return []
    
    if name_col is None or res_col is None:
        print(f"❌ Бағандар табылмады! name_col={name_col}, res_col={res_col}")
        return []
    
    print(f"📊 Бағандар: code={code_col}, name={name_col}, res={res_col}, sng={sng_col}, nonres={nonres_col}")
    
    results = []
    start_row = header_row_idx + 1
    
    for i in range(start_row, num_rows):
        row = df.iloc[i].tolist()
        
        if name_col >= len(row):
            continue
        raw_name = row[name_col]
        cleaned_name = clean_string(raw_name)
        
        if not cleaned_name or cleaned_name.lower() in ('nan', 'none'):
            continue
        
        name_lower = cleaned_name.lower()
        if name_lower.startswith(('раздел', 'блок')) or 'итого' in name_lower:
            continue
        
        res_val = row[res_col] if res_col < len(row) else None
        price_resident = clean_price(res_val)
        
        if sng_col is not None and sng_col < len(row):
            price_sng = clean_price(row[sng_col])
        else:
            price_sng = price_resident
            
        if nonres_col is not None and nonres_col < len(row):
            price_nonresident = clean_price(row[nonres_col])
        else:
            price_nonresident = price_resident
        
        # Егер барлық бағалар 0 болса, өткізіп жібер
        if price_resident == 0.0 and price_sng == 0.0 and price_nonresident == 0.0:
            continue
        
        service_code = None
        if code_col is not None and code_col < len(row):
            raw_code = row[code_col]
            cleaned_code = clean_string(raw_code)
            if cleaned_code and cleaned_code.lower() not in ('nan', 'none'):
                service_code = cleaned_code
        
        results.append({
            "service_code_source": service_code,
            "service_name_raw": cleaned_name,
            "price_resident_kzt": price_resident,
            "price_sng_kzt": price_sng,
            "price_nonresident_kzt": price_nonresident
        })
    
    return results
