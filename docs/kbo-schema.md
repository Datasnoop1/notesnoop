# KBO/CBE Open Data — CSV Schema Reference

Source: https://economie.fgov.be/en/themes/enterprises/crossroads-bank-enterprises/services-everyone/public-data-available-reuse/cbe-open-data
Cookbook: https://economie.fgov.be/sites/default/files/Files/Entreprises/BCE/Cookbook-BCE-Open-Data.pdf

## CSV Format

- Delimiter: comma `,`
- Text qualifier: double quotes `"`
- Decimal: period `.`
- Date format: `dd-mm-yyyy`
- NULL values: empty between delimiters
- Encoding: UTF-8

## Files in ZIP

### meta.csv
| Field | Type | Description |
|-------|------|-------------|
| Variable | text | Key name |
| Value | text | Key value |

Keys: SnapshotDate, ExtractTimestamp, ExtractType (full/update), ExtractNumber, Version

### enterprise.csv — 1 row per entity
| Field | Type | Format | Code Table | Required |
|-------|------|--------|------------|----------|
| EnterpriseNumber | text | 0xxx.xxx.xxx | — | yes |
| Status | text | XX | Status | yes |
| JuridicalSituation | text | XXX | JuridicalSituation | yes |
| TypeOfEnterprise | text | X | TypeOfEnterprise | yes |
| JuridicalForm | text | XXX | JuridicalForm | for legal persons |
| JuridicalFormCAC | text | XXX | JuridicalForm | optional |
| StartDate | date | dd-mm-yyyy | — | yes |

TypeOfEnterprise: 1 = legal person, 2 = natural person

### establishment.csv — 1 row per establishment unit
| Field | Type | Format | Required |
|-------|------|--------|----------|
| EstablishmentNumber | text | 9.999.999.999 | yes |
| StartDate | date | dd-mm-yyyy | yes |
| EnterpriseNumber | text | 0xxx.xxx.xxx | yes |

### denomination.csv — 1+ rows per entity
| Field | Type | Format | Code Table | Required |
|-------|------|--------|------------|----------|
| EntityNumber | text | enterprise or establishment number | — | yes |
| Language | text | 1 char | Language | yes |
| TypeOfDenomination | text | XXX | TypeOfDenomination | yes |
| Denomination | text | max 320 chars | — | yes |

Language codes: 1=FR, 2=NL, 3=DE, 4=EN
TypeOfDenomination: 001=official name, 002=commercial name, 003=abbreviation

### address.csv — 0-2 rows per entity
| Field | Type | Format | Code Table | Required |
|-------|------|--------|------------|----------|
| EntityNumber | text | — | — | yes |
| TypeOfAddress | text | XXXX | TypeOfAddress | yes |
| CountryNL | text | — | — | no (empty for Belgium) |
| CountryFR | text | — | — | no (empty for Belgium) |
| Zipcode | text | — | — | no |
| MunicipalityNL | text | — | — | no |
| MunicipalityFR | text | — | — | no |
| StreetNL | text | — | — | no |
| StreetFR | text | — | — | no |
| HouseNumber | text | — | — | no |
| Box | text | — | — | no |
| ExtraAddressInfo | text | — | — | no |
| DateStrikingOff | date | dd-mm-yyyy | — | no |

TypeOfAddress: REGO=registered office, BRAN=branch

### activity.csv — 1+ rows per entity
| Field | Type | Format | Code Table | Required |
|-------|------|--------|------------|----------|
| EntityNumber | text | — | — | yes |
| ActivityGroup | text | XXX | ActivityGroup | yes |
| NaceVersion | text | 2003/2008/2025 | — | yes |
| NaceCode | text | 5 or 7 digits | Nace2003/Nace2008/Nace2025 | yes |
| Classification | text | XXXX | Classification | yes |

Classification: MAIN=primary, SECO=secondary, AUXI=auxiliary

### contact.csv
| Field | Type | Format | Code Table | Required |
|-------|------|--------|------------|----------|
| EntityNumber | text | — | — | yes |
| EntityContact | text | 3 chars | EntityContact | yes |
| ContactType | text | 5 chars | ContactType | yes |
| Value | text | max 254 chars | — | yes |

ContactType: TEL=phone, EMAIL=email, WEB=website

### code.csv — lookup table for all codes
| Field | Type | Required |
|-------|------|----------|
| Category | text | yes |
| Code | text | yes |
| Language | text (DE/EN/FR/NL) | yes |
| Description | text | yes |

### branch.csv — foreign entity branches
| Field | Type | Format | Required |
|-------|------|--------|----------|
| Id | text | — | yes |
| StartDate | date | dd-mm-yyyy | yes |
| EnterpriseNumber | text | — | yes |

## Update File Logic

Update ZIPs contain paired files: `*_delete.csv` and `*_insert.csv`.

Processing order:
1. DELETE FROM table WHERE entity_number IN (SELECT entity_number FROM *_delete.csv)
2. INSERT INTO table SELECT * FROM *_insert.csv

The insert file contains ALL current rows for affected entities — not just changed rows.
code.csv in updates is always the full code table (replace entirely).
