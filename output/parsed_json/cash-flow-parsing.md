# ComboCurve cash-flow parsing

## Source and method

The ComboCurve `CASHFLOW` worksheet is exported through Excel COM to temporary
CSV. Its first row becomes the header. All remaining rows are converted to
record dictionaries. pandas `NaN` values are replaced by JSON `null`.

## Output

`cash_flow.json` contains 52 records under `cash_flow`.
The parser intentionally preserves the source worksheet's wide schema rather
than mapping it into the typed well schema.

## Fields found in this build

`10% After Income Tax Discount Cash Flow (M$)`, `10% Discount Cash Flow (M$)`, `10% Discount Net Operating Income (M$)`, `10% Discount Total Net CAPEX (M$)`, `20% After Income Tax Discount Cash Flow (M$)`, `20% Discount Cash Flow (M$)`, `20% Discount Net Operating Income (M$)`, `20% Discount Total Net CAPEX (M$)`, `Actual or Forecast Qualifier`, `Ad Valorem Tax (M$)`, `After Income Tax Cash Flow (M$)`, `Before Income Tax Cash Flow (M$)`, `CAPEX Qualifier`, `Combo Name`, `Created At`, `Date`, `Dates Qualifier`, `Differentials Qualifier`, `Expenses Qualifier`, `Forecast P Series Qualifier`, `Forecast Qualifier`, `Gas Shrinkage (%)`, `Gross Gas Sales Volume (MMCF)`, `Gross Gas Well Head Volume (MMCF)`, `Gross NGL Sales Volume (MBBL)`, `Gross Oil Sales Volume (MBBL)`, `Gross Oil Well Head Volume (MBBL)`, `Gross Water Well Head Volume (MBBL)`, `Gross Well Count`, `Group`, `Input Gas Price ($/MCF)`, `Input Oil Price ($/BBL)`, `NGL Yield (BBL/MMCF)`, `NPI Cash Flow (M$)`, `NRI Oil (%)`, `NRI Well Count`, `Net BOE Sales Volume (MBBL)`, `Net Gas Revenue (M$)`, `Net Gas Sales Volume (MMCF)`, `Net NGL Revenue (M$)`, `Net NGL Sales Volume (MBBL)`, `Net Oil Revenue (M$)`, `Net Oil Sales Volume (MBBL)`, `Net Operating Income (M$)`, `Operations Qualifier`, `Ownership and Reversion Qualifier`, `Pricing Qualifier`, `Production Taxes Qualifier`, `Project Name`, `Realized Gas Price ($/MCF)`, `Realized NGL Price ($/BBL)`, `Realized Oil Price ($/BBL)`, `Reserves Category Qualifier`, `Risking Qualifier`, `Scenario Name`, `Schedule Qualifier`, `State Income Tax (M$)`, `Stream Properties Qualifier`, `Taxable Income (M$)`, `Total Expense (M$)`, `Total Fixed Expense (M$)`, `Total Gas Variable Expense (M$)`, `Total Gross Investment (M$)`, `Total Net Intangible Investment (M$)`, `Total Net Investment (M$)`, `Total Net Revenue (M$)`, `Total Net Tangible Investment (M$)`, `Total Oil Variable Expense (M$)`, `Total Production Tax (M$)`, `Total Severance Tax (M$)`, `Total Variable Expense (M$)`, `User Name`, `WI Oil (%)`, `WI Well Count`, `Water Disposal Expense (M$)`

## Important behavior

- No PV-10 is recalculated from these rows.
- No column-specific numeric coercion is applied to this dataset.
- Column names and values follow the exported worksheet.
- The output is raw normalized transport data for later economics validation.
