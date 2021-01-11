from can_tools.scrapers.official import CDCCovidDataTracker, CDCVaccineTotal, CDCVaccineModerna, CDCVaccinePfizer 
import pandas as pd 
import csv
import sys

if len(sys.argv) == 1: 
    print("no args supplied. bye")
    quit()

prompt = sys.argv[1]
if prompt == "moderna":
    scraper = CDCVaccineModerna()
elif prompt == "pfizer":
    scraper = CDCVaccinePfizer()
elif prompt == "total":
    scraper = CDCVaccineTotal()
else:
    print("type correctly lol. bye")
    quit()

df = scraper.normalize(scraper.fetch())
print(df)
for val in df["loc_name"].unique():
    print(val)

if sys.argv[len(sys.argv)-1] == "csv":
    print("\nwriting to csv...")    
    fl = prompt + ".csv"
    df.to_csv(fl, index=True)
    print("done +++")