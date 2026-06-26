from xlsx_parser import parse_csv_excel
from docx_parser import parse_docx
import os

def parse_file(file_path):
    """Файл типіне қарай парсерді шақырады"""
    if not os.path.exists(file_path):
        print(f"❌ Файл жоқ: {file_path}")
        return []
    
    if file_path.endswith(('.xlsx', '.xls')):
        return parse_csv_excel(file_path)
    elif file_path.endswith('.docx'):
        return parse_docx(file_path)
    else:
        print(f"⚠️ Бейтаныс формат: {file_path}")
        return []

def save_results(results, output_file):
    """Нәтижені JSON файлына сақтайды"""
    import json
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"✅ Нәтиже сақталды: {output_file}")

if __name__ == "__main__":
    print("=" * 60)
    print("🌐 БАРЛЫҚ ФАЙЛДАРДЫ ПАРСИНГ ЖАСАУ")
    print("=" * 60)
    
    files = [
        'Клиника 6 прайс 2026.xlsx',
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
            print(f"Мысалы: {results[0]['service_name_raw'][:35]}... -> {results[0]['price_resident_kzt']}")
            all_results.extend(results)
        else:
            print(f"❌ Ешқандай мәлімет табылмады")
    
    print("\n" + "=" * 60)
    print(f"📊 БАРЛЫҒЫ {len(all_results)} ЖОЛ ТАБЫЛДЫ")
    print("=" * 60)
    
    # Нәтижені сақта
    save_results(all_results, 'parsed_results.json')
    
    # Қысқаша статистика
    print("\n📊 СТАТИСТИКА:")
    print(f"Барлығы: {len(all_results)} жол")
    
    # Кодтары бар жолдар
    with_code = sum(1 for x in all_results if x.get('service_code_source'))
    print(f"Коды бар: {with_code} жол")
    print(f"Коды жоқ: {len(all_results) - with_code} жол")
