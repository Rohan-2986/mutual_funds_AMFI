# from apps.mutual_funds.services.amfi_client import download_nav_report
#
#
# data = download_nav_report("08-Aug-2026")
#
# print(data)


# ******************shows number of lines and characters# ******************
#
# from apps.mutual_funds.services.amfi_client import download_nav_report
#
#
# data = download_nav_report("6-Aug-2026")
#
# with open("amfi_raw_data.txt", "w", encoding="utf-8") as file:
#     file.write(data)
#
# print("AMFI data downloaded successfully.")
# print("Total characters:", len(data))
# print("Total lines:", len(data.splitlines()))
#


# ******************shows number of lines and characters and schemas# ******************

# from apps.mutual_funds.services.amfi_client import download_nav_report
#
#
# data = download_nav_report("08-Aug-2026")
#
# with open("amfi_raw_data.txt", "w", encoding="utf-8") as file:
#     file.write(data)
#
#
# lines = data.splitlines()
#
# print("Total characters:", len(data))
# print("Total lines:", len(lines))
#
# scheme_rows = 0
#
# for line in lines:
#     parts = line.split(";")
#
#     if parts and parts[0].strip().isdigit():
#         scheme_rows += 1
#
# print("Possible scheme records:", scheme_rows)

# ****************** shows first five records means funds # ******************
from apps.mutual_funds.services.amfi_client import download_nav_report
from apps.mutual_funds.services.parser import parse_amfi_report

#
# raw_data = download_nav_report("08-Aug-2026")
#
# records = parse_amfi_report(raw_data)
#
# print("Total parsed records:", len(records))
#
# print("\nFirst 5 records:\n")
#
# for record in records[:5]:
#     print(record)
#     print("\n\n")

