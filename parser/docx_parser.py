from docx import Document
import re

def clean_price(val):
    if val is None:
        return 0.0
    s = str(val).strip()
    s = re.sub(r'\s+', '', s)
    s = re.sub(r'[^\d.,]', '', s)
    s = s.replace(',', '.')
    try:
        return float(s)
    except:
        return 0.0

def clean_string(val):
    if val is None:
        return ""
    s = str(val).strip()
    s = re.sub(r'\s+', ' ', s)
    return s

def parse_docx(file_path):
    try:
        doc = Document(file_path)
        print(f"✅ DOCX файл ашылды: {file_path}")
    except Exception as e:
        print(f"❌ Қате: {e}")
        return []
    
    results = []
    
    for table in doc.tables:
        header_row = None
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any('код' in c.lower() for c in cells) and any('наименование' in c.lower() for c in cells):
                header_row = cells
                break
        
        if header_row is None:
            continue
        
        code_idx = None
        name_idx = None
        price_idx = None
        
        for i, cell in enumerate(header_row):
            lower = cell.lower()
            if 'код' in lower and 'наименование' not in lower:
                code_idx = i
            elif 'наименование' in lower:
                name_idx = i
            elif 'стоимость' in lower or 'цена' in lower or 'тенге' in lower:
                price_idx = i
        
        if name_idx is None or price_idx is None:
            continue
        
        for row in table.rows[1:]:
            cells = [cell.text.strip() for cell in row.cells]
            if len(cells) <= max(name_idx, price_idx):
                continue
            
            name = clean_string(cells[name_idx]) if name_idx < len(cells) else ''
            if not name or name.lower().startswith(('раздел', 'блок')):
                continue
            
            price = clean_price(cells[price_idx]) if price_idx < len(cells) else 0.0
            if price == 0.0:
                continue
            
            code = clean_string(cells[code_idx]) if code_idx is not None and code_idx < len(cells) else None
            
            results.append({
                "service_code_source": code,
                "service_name_raw": name,
                "price_resident_kzt": price,
                "price_sng_kzt": price,
                "price_nonresident_kzt": price
            })
    
    return results
