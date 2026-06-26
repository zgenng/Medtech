import os
import json
import pandas as pd
import re
from xlsx_parser import parse_csv_excel
from docx_parser import parse_docx

# ============================================================
# parse_clinic8 - КЛИНИКА 8 ҮШІН АРНАЙЫ ПАРСЕР
# ============================================================
def parse_clinic8(file_path):
    print(f"🔧 Клиника 8 парсері іске қосылды")
    
    df = pd.read_excel(file_path, header=None, engine='openpyxl')
    results = []
    
    def clean_price(val):
        if pd.isna(val):
            return 0.0
        s = str(val).strip()
        s = re.sub(r'\s+', '', s)
        s = re.sub(r'[^\d.]', '', s)
        if s == '':
            return 0.0
        try:
            return float(s)
        except:
            return 0.0

    def clean_string(val):
        if pd.isna(val):
            return ""
        s = str(val).strip()
        s = re.sub(r'\s+', ' ', s)
        return s

    for i in range(20, len(df)):
        row = df.iloc[i].tolist()
        if len(row) < 5:
            continue
            
        name = clean_string(row[1])
        if not name:
            continue
            
        if name.upper() == name:
            continue
        if name.startswith(('ПРИЕМ', 'ОНЛАЙН', 'АМБУЛАТОРНО', 'РАЗДЕЛ', 'БЛОК')):
            continue
        if name in ('ПРИЕМ ВРАЧА', 'АБОНЕМЕНТНАЯ СИСТЕМА', 'ГРУППОВЫЕ ЗАНЯТИЯ'):
            continue
            
        code = clean_string(row[2])
        price = clean_price(row[4])
        
        if price == 0.0:
            continue
            
        results.append({
            "service_code_source": code if code else None,
            "service_name_raw": name,
            "price_resident_kzt": price,
            "price_sng_kzt": price,
            "price_nonresident_kzt": price
        })
    
    print(f"✅ Клиника 8: {len(results)} жол табылды")
    return results

# ============================================================
# parse_clinic7 - КЛИНИКА 7 ҮШІН АРНАЙЫ ПАРСЕР
# ============================================================
def parse_clinic7(file_path):
    print(f"🔧 Клиника 7 парсері іске қосылды")
    
    df = pd.read_excel(file_path, header=None)
    results = []
    
    def clean_price(val):
        if pd.isna(val):
            return 0.0
        s = str(val).strip()
        s = re.sub(r'\s+', '', s)
        s = re.sub(r'[^\d.]', '', s)
        if s == '':
            return 0.0
        try:
            return float(s)
        except:
            return 0.0

    def clean_string(val):
        if pd.isna(val):
            return ""
        s = str(val).strip()
        s = re.sub(r'\s+', ' ', s)
        return s

    for i in range(7, len(df)):
        row = df.iloc[i].tolist()
        if len(row) < 6:
            continue
            
        name = clean_string(row[1])
        if not name:
            continue
            
        if name.upper() == name:
            continue
        if name.startswith(('ПРИЕМ', 'ОНЛАЙН', 'АМБУЛАТОРНО')):
            continue
        if name in ('ПРИЕМ ВРАЧА', 'ПРИЕМ ВРАЧА '):
            continue
            
        price_res = clean_price(row[3])
        price_sng = clean_price(row[4])
        price_nonres = clean_price(row[5])
        
        if price_res == 0.0 and price_sng == 0.0 and price_nonres == 0.0:
            continue
            
        results.append({
            "service_code_source": None,
            "service_name_raw": name,
            "price_resident_kzt": price_res,
            "price_sng_kzt": price_sng,
            "price_nonresident_kzt": price_nonres
        })
    
    print(f"✅ Клиника 7: {len(results)} жол табылды")
    return results

# ============================================================
# parse_file
# ============================================================
def parse_file(file_path):
    if not os.path.exists(file_path):
        print(f"❌ Файл жоқ: {file_path}")
        return []
    
    if 'Клиника 8' in file_path:
        return parse_clinic8(file_path)
    elif 'Клиника 7' in file_path:
        return parse_clinic7(file_path)
    elif file_path.endswith(('.xlsx', '.xls')):
        return parse_csv_excel(file_path)
    elif file_path.endswith('.docx'):
        return parse_docx(file_path)
    else:
        print(f"⚠️ Бейтаныс формат: {file_path}")
        return []

# ============================================================
# save_results
# ============================================================
def save_results(results, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"✅ Нәтиже сақталды: {output_file}")

# ============================================================
# НЕГІЗГІ БЛОК
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("🌐 БАРЛЫҚ ФАЙЛДАРДЫ ПАРСИНГ ЖАСАУ")
    print("=" * 60)
    
    files = [
        'Клиника 6 прайс 2026.xlsx',
        'Клиника 7_Прайс 2026.xls',
        'Клиника 8 2026.xlsx',
        'Клиника 1 прайс 2024.docx'
    ]
    
    all_results = []
    
    for file_path in files:
        print(f"\n📄 {file_path}")
        print("-" * 40)
        results = parse_file(file_path)
        
        if results:
            print(f"✅ {len(results)} жол табылды")
            if results:
                print(f"Мысалы: {results[0]['service_name_raw'][:35]}... -> {results[0]['price_resident_kzt']}")
            all_results.extend(results)
        else:
            print(f"❌ Ешқандай мәлімет табылмады")
    
    print("\n" + "=" * 60)
    print(f"📊 БАРЛЫҒЫ {len(all_results)} ЖОЛ ТАБЫЛДЫ")
    print("=" * 60)
    
    save_results(all_results, 'parsed_results.json')
    
    with_code = sum(1 for x in all_results if x.get('service_code_source'))
    with_sng = sum(1 for x in all_results if x.get('price_sng_kzt', 0) > 0)
    
    print("\n📊 СТАТИСТИКА:")
    print(f"Барлығы: {len(all_results)} жол")
    print(f"Коды бар: {with_code} жол")
    print(f"Коды жоқ: {len(all_results) - with_code} жол")
    print(f"СНГ бағасы бар: {with_sng} жол")
