"""
Utility script to generate a sample iLO Excel inventory template.
"""

from ilo_updater.excel_parser import generate_sample_excel

if __name__ == "__main__":
    output_file = "sample_inventory.xlsx"
    generate_sample_excel(output_file)
    print(f"[SUCCESS] Sample Excel inventory template generated: {output_file}")
