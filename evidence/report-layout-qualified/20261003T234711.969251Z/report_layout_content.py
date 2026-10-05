"""Independent, section-bound completeness checks for synthetic report PDFs."""
import re


def verify_content(reader, specimen):
    bodies = []
    for page in reader.pages:
        lines = page.extract_text().splitlines()
        body = '\n'.join(line for line in lines
                         if not re.fullmatch(r'Page \d+ of \d+', line.strip())).strip()
        if not body:
            raise RuntimeError('Report contains a blank or footer-only page')
        bodies.append(body)
    text = '\n'.join(bodies)
    start = text.find('AI and software inventory')
    stop = text.find('Overall risk overview', start + 1)
    if start < 0 or stop < 0:
        raise RuntimeError('Report inventory section is missing or unterminated')
    inventory = ' '.join(text[start:stop].split())
    count = {'long-table': 80, 'multi-tool': 8}.get(specimen, 0)
    for number in range(1, count + 1):
        label = ('Synthetic table tool ' + format(number, '03d')
                 if specimen == 'long-table' else 'Synthetic tool ' + str(number))
        if not re.search(re.escape(label) + r'\s*\(', inventory):
            raise RuntimeError('Inventory section lost a synthetic row: ' + label)
    if specimen == 'long-table' and inventory.count('Monthly cost') < 2:
        raise RuntimeError('Long inventory table did not repeat its headers')
    if specimen == 'long-input' and 'Müller & García' not in text:
        raise RuntimeError('Latin customer-name glyphs were lost')
    return {'pages': len(bodies), 'nonempty_pages': True,
            'inventory_section_complete': True}


def verify_receipt(receipt):
    if receipt.get('qualification_passed') is not True:
        raise RuntimeError('Layout qualification did not pass')
    checks = receipt.get('content_checks', {})
    if set(checks) != {'long-input', 'multi-tool', 'long-table'}:
        raise RuntimeError('Layout receipt specimen set is incomplete')
    for check in checks.values():
        if (check.get('nonempty_pages') is not True
                or check.get('inventory_section_complete') is not True
                or type(check.get('pages')) is not int or check['pages'] < 1):
            raise RuntimeError('Layout receipt contains failed content checks')
    geometry = receipt.get('geometry', {})
    columns = geometry.get('table_columns', [])
    if (geometry.get('viewport') != 688 or len(columns) != 5
            or geometry.get('document_width', 10000) > 689 or min(columns) < 90):
        raise RuntimeError('Layout receipt contains failed geometry checks')
