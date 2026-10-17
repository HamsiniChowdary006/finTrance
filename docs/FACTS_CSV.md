# Manual facts CSV

`python -m agent.cli facts import --file facts.csv` accepts:

```csv
ticker,metric,period,value,unit,source_file,page,quote
SYNTHETIC,gross_advances,Q1FY25,1000,INR crore,synthetic.pdf,1,"SYNTHETIC gross advances 1,000 crore"
SYNTHETIC,gross_npa,Q1FY25,20,INR crore,synthetic.pdf,1,"SYNTHETIC gross NPA 20 crore"
SYNTHETIC,gnpa_pct,Q1FY25,2,%,synthetic.pdf,1,"SYNTHETIC GNPA % 2"
```

The rows above are **SYNTHETIC examples**, not company data. A registered,
parseable source with a matching quote is assigned normal manual confidence.
Missing or unparseable sources are retained as `manual_unverified` facts with
low confidence and are shown in the import rejection output.
