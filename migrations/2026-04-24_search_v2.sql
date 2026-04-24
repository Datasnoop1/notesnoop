-- =======================================================================
-- DataSnoop search V2 migration — 2026-04-24
--
-- Idempotent. Safe to re-run.
--
-- The migration is split into SIX transactions so any single table
-- rewrite can be retried without redoing the others, and the planner
-- picks up stats incrementally. On a prod-sized DB (3 M
-- `administrator` rows, 3.5 M `denomination` rows) expect:
--   - Phase 0 (extensions + functions + reference tables): <5 s
--   - Phase 1 (company_info rewrite + indexes):              10-30 s
--   - Phase 2 (administrator rewrite + 3 GIN indexes):       3-6 min
--   - Phase 3 (shareholder rewrite + 3 GIN indexes):         1-3 min
--   - Phase 4 (staatsblad_event rewrite + 3 GIN indexes):    30-90 s
--   - Phase 5 (denomination rewrite + 1 GIN index):          3-7 min
-- Total ~8-17 min. During each phase, writes to the affected table
-- BLOCK. Pause the semantic worker + KBO updater beforehand per the
-- operator runbook. ANALYZE runs per-phase, outside each transaction.
--
-- IMPORTANT: do NOT pass this file to `psql -1` — that wraps the
-- entire file in one transaction and the per-phase splits lose their
-- value. Use `psql -v ON_ERROR_STOP=1 -f migrations/2026-04-24_search_v2.sql`.
-- =======================================================================

-- -----------------------------------------------------------------------
-- Phase 0 — extensions + functions + reference tables (fast)
-- -----------------------------------------------------------------------
BEGIN;

-- -----------------------------------------------------------------------
-- 1. Extensions
-- -----------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;   -- provides dmetaphone()
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- -----------------------------------------------------------------------
-- 2. IMMUTABLE wrappers so functions can be used in generated columns
--    and expression indexes. `unaccent()` is STABLE by default which
--    blocks index-building; f_unaccent asserts immutability.
-- -----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION f_unaccent(text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT public.unaccent('public.unaccent', $1)
$$;

-- Canonical normaliser — matches backend/search_normalization.py::normalize_name
-- exactly. Strips TRAILING Belgian + foreign legal suffixes. The '$'
-- anchor is critical: without it we would strip the leading "NV" from
-- names like "NVidia Belgium".
CREATE OR REPLACE FUNCTION search_normalize(s text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT NULLIF(
    TRIM(
      REGEXP_REPLACE(
        LOWER(f_unaccent(
          REGEXP_REPLACE(
            COALESCE(s, ''),
            '[[:space:][:punct:]]*(' ||
              'nv|sa|bvba|sprl|bv|srl|cvba|scrl|vof|snc|se|scs|gcv|' ||
              'comm\.?\s*v|scomm|asbl|vzw|aisbl|ivzw|' ||
              'gmbh|ag|ltd|inc|sas|sarl|llc|plc|corp|spa|kg|ohg|ug|eurl' ||
            ')[[:space:][:punct:]]*$',
            '', 'gi'
          )
        )),
        '\s+', ' ', 'g'
      )
    ),
    ''
  )
$$;

-- Sorted-tokens reversed key. "tim braet" and "braet tim" both → "braet tim".
CREATE OR REPLACE FUNCTION search_name_reversed(s text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT NULLIF(
    ARRAY_TO_STRING(
      (SELECT ARRAY_AGG(tok ORDER BY tok)
       FROM regexp_split_to_table(COALESCE(search_normalize(s), ''), '\s+') tok
       WHERE tok <> ''),
      ' '
    ),
    ''
  )
$$;

-- Double-Metaphone key per token, space-joined. Empty if input empty.
-- dmetaphone() from `fuzzystrmatch`.
CREATE OR REPLACE FUNCTION search_phonetic_key(s text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT NULLIF(
    ARRAY_TO_STRING(
      (SELECT ARRAY_AGG(dmetaphone(tok))
       FROM regexp_split_to_table(COALESCE(search_normalize(s), ''), '\s+') tok
       WHERE tok <> ''),
      ' '
    ),
    ''
  )
$$;


-- -----------------------------------------------------------------------
-- 5. KBO juridical-form category lookup. 146 codes. Upsert lets us
--    re-seed if the taxonomy is refreshed later.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS juridical_form_category (
  code      text PRIMARY KEY,
  label_nl  text NOT NULL,
  label_fr  text NOT NULL,
  category  text NOT NULL CHECK (category IN ('commercial','nonprofit','public','other'))
);

INSERT INTO juridical_form_category (code, label_nl, label_fr, category) VALUES
  ('001', 'Europese Coöperatieve Vennootschap',                         'Société coopérative européenne',                                   'commercial'),
  ('002', 'Organisme voor de Financiering van Pensioenen',              'Organisme de financement de pensions',                             'other'),
  ('003', 'BTW-eenheid',                                                 'Unité TVA',                                                        'other'),
  ('006', 'Coöperatieve vennootschap met onbeperkte aansprakelijkheid', 'Société coopérative à responsabilité illimitée',                   'commercial'),
  ('007', 'CVOA bij wijze van deelneming',                               'Coopérative à responsabilité illimitée, participation',            'commercial'),
  ('008', 'Coöperatieve vennootschap met beperkte aansprakelijkheid',   'Société coopérative à responsabilité limitée',                     'commercial'),
  ('009', 'CVBA bij wijze van deelneming',                               'SCRL, coopérative de participation',                               'commercial'),
  ('010', 'Eenpersoons BVBA',                                            'SPRL unipersonnelle',                                              'commercial'),
  ('011', 'Vennootschap onder firma',                                    'Société en nom collectif',                                         'commercial'),
  ('012', 'Gewone commanditaire vennootschap',                           'Société en commandite simple',                                     'commercial'),
  ('013', 'Commanditaire vennootschap op aandelen',                      'Société en commandite par actions',                                'commercial'),
  ('014', 'Naamloze vennootschap',                                       'Société anonyme',                                                  'commercial'),
  ('015', 'BVBA',                                                        'SPRL',                                                             'commercial'),
  ('016', 'Coöperatieve vennootschap (oud statuut)',                    'Société coopérative (ancien statut)',                              'commercial'),
  ('017', 'Vereniging zonder winstoogmerk',                              'Association sans but lucratif',                                    'nonprofit'),
  ('018', 'Instelling van openbaar nut',                                 'Etablissement d''utilité publique',                                'nonprofit'),
  ('019', 'Ziekenfonds / Mutualiteit',                                   'Mutualité',                                                        'nonprofit'),
  ('020', 'Beroepsvereniging',                                           'Union professionnelle',                                            'nonprofit'),
  ('021', 'Onderlinge verzekeringsvereniging (privaatrecht)',            'Association d''assurances mutuelles (droit privé)',                'nonprofit'),
  ('022', 'Internationale wetenschappelijke organisatie',                'Organisation scientifique internationale',                         'nonprofit'),
  ('023', 'Buitenlandse privaatrechtelijke vereniging',                  'Association étrangère privée',                                     'nonprofit'),
  ('025', 'Landbouwvennootschap',                                        'Société agricole',                                                 'commercial'),
  ('026', 'Private stichting',                                           'Fondation privée',                                                 'nonprofit'),
  ('027', 'Europese vennootschap (Societas Europaea)',                   'Société européenne',                                               'commercial'),
  ('028', 'Instelling zonder winstoogmerk',                              'Institution sans but lucratif',                                    'nonprofit'),
  ('029', 'Stichting van openbaar nut',                                  'Fondation d''utilité publique',                                    'nonprofit'),
  ('030', 'Buitenlandse entiteit',                                       'Entité étrangère',                                                 'other'),
  ('040', 'Kongolese vennootschap',                                      'Société congolaise',                                               'other'),
  ('051', 'Andere privaatrechtelijke vorm met rechtspersoonlijkheid',    'Autre forme de droit privé avec personnalité juridique',           'other'),
  ('060', 'Economisch samenwerkingsverband',                             'Groupement d''intérêt économique',                                 'commercial'),
  ('065', 'Europees economisch samenwerkingsverband',                    'Groupement européen d''intérêt économique',                        'commercial'),
  ('070', 'Vereniging van mede-eigenaars',                               'Association des copropriétaires',                                  'other'),
  ('106', 'CVOA van publiek recht',                                      'Coopérative à responsabilité illimitée de droit public',           'public'),
  ('107', 'CVOA van publiek recht, deelneming',                          'Coopérative à responsabilité illimitée, participation, public',    'public'),
  ('108', 'CVBA van publiek recht',                                      'Coopérative à responsabilité limitée de droit public',             'public'),
  ('109', 'CVBA van publiek recht, deelneming',                          'SCRL de droit public, coopérative de participation',               'public'),
  ('110', 'Rijk, Provincie, Gewest, Gemeenschap',                        'État, Province, Région, Communauté',                               'public'),
  ('114', 'Naamloze vennootschap van publiek recht',                     'Société anonyme de droit public',                                  'public'),
  ('116', 'Coöperatieve vennootschap van publiek recht (oud)',          'Société coopérative de droit public (ancien)',                     'public'),
  ('117', 'VZW van publiek recht',                                       'ASBL de droit public',                                             'public'),
  ('121', 'Onderlinge verzekeringsvereniging van publiek recht',         'Association d''assurances mutuelles de droit public',              'public'),
  ('123', 'Beroepsvereniging / Orde',                                    'Corporation professionnelle / Ordre',                              'public'),
  ('124', 'Openbare instelling',                                         'Etablissement public',                                             'public'),
  ('125', 'Internationale vereniging zonder winstoogmerk',               'Association internationale sans but lucratif',                     'nonprofit'),
  ('126', 'Openbaar centrum voor maatschappelijk welzijn',               'Centre public d''action sociale',                                  'public'),
  ('127', 'Berg van Barmhartigheid',                                     'Monts-de-Piété',                                                   'public'),
  ('128', 'Eredienst / Kerkfabriek',                                     'Temporel des cultes',                                              'public'),
  ('129', 'Polder / Watering',                                           'Polder / wateringue',                                              'public'),
  ('151', 'Andere rechtsvorm',                                           'Autre forme légale',                                               'other'),
  ('155', 'Lokale politiezone',                                          'Zone de police locale',                                            'public'),
  ('160', 'Buitenlandse of internationale publieke organisatie',         'Organisme public étranger ou international',                       'public'),
  ('200', 'Vennootschap in oprichting',                                  'Société en formation',                                             'commercial'),
  ('206', 'Burgerlijke vennootschap CVOA',                               'Société civile CVOA',                                              'commercial'),
  ('208', 'Burgerlijke vennootschap CVBA',                               'Société civile CVBA',                                              'commercial'),
  ('211', 'Burgerlijke vennootschap VOF',                                'Société civile SNC',                                               'commercial'),
  ('212', 'Burgerlijke vennootschap Comm.V',                             'Société civile SCS',                                               'commercial'),
  ('213', 'Burgerlijke vennootschap Comm.VA',                            'Société civile SCA',                                               'commercial'),
  ('214', 'Burgerlijke vennootschap NV',                                 'Société civile SA',                                                'commercial'),
  ('215', 'Burgerlijke vennootschap BVBA',                               'Société civile SPRL',                                              'commercial'),
  ('217', 'Europese politieke partij',                                   'Parti politique européen',                                         'nonprofit'),
  ('218', 'Europese politieke stichting',                                'Fondation politique européenne',                                   'nonprofit'),
  ('225', 'Burgerlijke Vennootschap Landbouw',                           'Société civile agricole',                                          'commercial'),
  ('230', 'Buitenlandse entiteit met BE-vastgoed',                       'Entité étrangère avec immobilier BE',                              'other'),
  ('235', 'Buitenlandse entiteit, BTW-rep',                              'Entité étrangère, rep. TVA',                                       'other'),
  ('260', 'ESV zonder zetel, BE-vestiging',                              'GIE sans siège, établissement BE',                                 'commercial'),
  ('265', 'EESV zonder zetel, BE-vestiging',                             'GEIE sans siège, établissement BE',                                'commercial'),
  ('301', 'Federale overheidsdienst',                                    'Service public fédéral',                                           'public'),
  ('302', 'POD',                                                         'SPP',                                                              'public'),
  ('303', 'Andere federale dienst',                                      'Autre service fédéral',                                            'public'),
  ('310', 'Vlaamse overheid',                                            'Autorité flamande',                                                'public'),
  ('320', 'Waalse overheid',                                             'Autorité wallonne',                                                'public'),
  ('325', 'IVZW van publiek recht',                                      'AISBL de droit public',                                            'public'),
  ('330', 'Brusselse overheid',                                          'Autorité bruxelloise',                                             'public'),
  ('340', 'Franse Gemeenschap',                                          'Communauté française',                                             'public'),
  ('350', 'Duitstalige Gemeenschap',                                     'Communauté germanophone',                                          'public'),
  ('370', 'Ministerie van Economische Zaken (legacy)',                   'Ministère Affaires économiques (legacy)',                          'public'),
  ('371', 'Ministerie Buitenlandse Zaken (legacy)',                      'Ministère Affaires étrangères (legacy)',                           'public'),
  ('372', 'Ministerie Landbouw (legacy)',                                'Ministère Agriculture (legacy)',                                   'public'),
  ('373', 'Ministerie Middenstand (legacy)',                             'Ministère Classes moyennes (legacy)',                              'public'),
  ('374', 'Ministerie Verkeerswerken (legacy)',                          'Ministère Communications (legacy)',                                'public'),
  ('375', 'Ministerie Defensie (legacy)',                                'Ministère Défense (legacy)',                                       'public'),
  ('376', 'Ministerie Onderwijs (legacy)',                               'Ministère Éducation (legacy)',                                     'public'),
  ('377', 'Ministerie Tewerkstelling (legacy)',                          'Ministère Emploi (legacy)',                                        'public'),
  ('378', 'Ministerie Financiën (legacy)',                               'Ministère Finances (legacy)',                                      'public'),
  ('379', 'Ministerie Binnenlandse Zaken (legacy)',                      'Ministère Intérieur (legacy)',                                     'public'),
  ('380', 'Ministerie Justitie (legacy)',                                'Ministère Justice (legacy)',                                       'public'),
  ('381', 'Ministerie Sociale Voorzorg (legacy)',                        'Ministère Prévoyance sociale (legacy)',                            'public'),
  ('382', 'Ministerie Volksgezondheid (legacy)',                         'Ministère Santé publique (legacy)',                                'public'),
  ('383', 'Diensten Eerste Minister (legacy)',                           'Services Premier Ministre (legacy)',                               'public'),
  ('384', 'Ministerie Infrastructuur (legacy)',                          'Ministère Infrastructure (legacy)',                                'public'),
  ('385', 'Ministerie Vlaamse Gemeenschap (legacy)',                     'Ministère Communauté flamande (legacy)',                           'public'),
  ('386', 'Ministerie Franse Gemeenschap (legacy)',                      'Ministère Communauté française (legacy)',                          'public'),
  ('387', 'Ministerie Brussel (legacy)',                                 'Ministère Bruxelles (legacy)',                                     'public'),
  ('388', 'Ministerie Waals Gewest (legacy)',                            'Ministère Région wallonne (legacy)',                               'public'),
  ('389', 'Ministerie Duitstalige Gemeenschap (legacy)',                 'Ministère Communauté germanophone (legacy)',                       'public'),
  ('390', 'Ministerie Ambtenarenzaken (legacy)',                         'Ministère Fonction publique (legacy)',                             'public'),
  ('391', 'Ministerie Middenstand & Landbouw (legacy)',                  'Ministère Classes moyennes & Agriculture (legacy)',                'public'),
  ('392', 'Ministerie Sociale Zaken & Milieu (legacy)',                  'Ministère Affaires sociales & Environnement (legacy)',             'public'),
  ('393', 'Andere (ministeries)',                                        'Divers (ministères)',                                              'public'),
  ('400', 'Provinciale overheid',                                        'Autorité provinciale',                                             'public'),
  ('401', 'RSZ PPO',                                                     'ONSS-APL',                                                         'public'),
  ('411', 'Stad / gemeente',                                             'Ville / commune',                                                  'public'),
  ('412', 'OCMW',                                                        'CPAS',                                                             'public'),
  ('413', 'Lokale politiezone',                                          'Zone de police locale',                                            'public'),
  ('414', 'Intercommunale',                                              'Intercommunale',                                                   'public'),
  ('415', 'Projectvereniging',                                           'Association de projet',                                            'public'),
  ('416', 'Dienstverlenende vereniging',                                 'Association prestataire de services',                              'public'),
  ('417', 'Opdrachthoudende vereniging',                                 'Association chargée de mission',                                   'public'),
  ('418', 'Autonoom gemeentebedrijf',                                    'Régie communale autonome',                                         'public'),
  ('419', 'Autonoom provinciebedrijf',                                   'Régie provinciale autonome',                                       'public'),
  ('420', 'Vereniging van OCMW''s',                                      'Association de CPAS',                                              'public'),
  ('421', 'Prezone',                                                     'Prézone',                                                          'public'),
  ('422', 'Hulpverleningszone',                                          'Zone de secours',                                                  'public'),
  ('451', 'RVP-organisme',                                               'Organisme ONP',                                                    'public'),
  ('452', 'Pensioen-organisme',                                          'Organisme Pensions',                                               'public'),
  ('453', 'Beursgenoteerde buitenlandse entiteit',                       'Société étrangère cotée',                                          'other'),
  ('454', 'Buitenlandse entiteit zonder RP met BE-vastgoed',             'Entité étrangère sans PJ avec immobilier BE',                      'other'),
  ('506', 'CVOA met sociaal oogmerk',                                    'CVOA à finalité sociale',                                          'nonprofit'),
  ('508', 'CVBA met sociaal oogmerk',                                    'CVBA à finalité sociale',                                          'nonprofit'),
  ('510', 'Eenpersoons BVBA sociaal oogmerk',                            'SPRL unipersonnelle finalité sociale',                             'nonprofit'),
  ('511', 'VOF sociaal oogmerk',                                         'SNC finalité sociale',                                             'nonprofit'),
  ('512', 'Comm.V sociaal oogmerk',                                      'SCS finalité sociale',                                             'nonprofit'),
  ('513', 'Comm.VA sociaal oogmerk',                                     'SCA finalité sociale',                                             'nonprofit'),
  ('514', 'NV sociaal oogmerk',                                          'SA finalité sociale',                                              'nonprofit'),
  ('515', 'BVBA sociaal oogmerk',                                        'SPRL finalité sociale',                                            'nonprofit'),
  ('560', 'ESV sociaal oogmerk',                                         'GIE finalité sociale',                                             'nonprofit'),
  ('606', 'CVOA sociaal oogmerk (WVV)',                                  'CVOA finalité sociale (CSA)',                                      'nonprofit'),
  ('608', 'CVBA sociaal oogmerk (WVV)',                                  'CVBA finalité sociale (CSA)',                                      'nonprofit'),
  ('610', 'Besloten Vennootschap (BV/SRL, WVV)',                         'Société à responsabilité limitée (CSA)',                           'commercial'),
  ('612', 'Commanditaire vennootschap (WVV)',                            'Société en commandite (CSA)',                                      'commercial'),
  ('614', 'NV sociaal oogmerk (WVV)',                                    'SA finalité sociale (CSA)',                                        'nonprofit'),
  ('616', 'BV van publiek recht',                                        'SRL de droit public',                                              'public'),
  ('617', 'Comm.V van publiek recht',                                    'SComm de droit public',                                            'public'),
  ('651', 'Andere vorm sociaal oogmerk, publiek recht',                  'Autre forme finalité sociale de droit public',                     'public'),
  ('701', 'Onrechtmatige handelsvennootschap',                           'Société commerciale irrégulière',                                  'commercial'),
  ('702', 'Maatschap',                                                   'Société de droit commun',                                          'commercial'),
  ('703', 'Tijdelijke handelsvennootschap',                              'Société momentanée',                                               'commercial'),
  ('704', 'Stille handelsvennootschap',                                  'Société interne',                                                  'commercial'),
  ('706', 'Coöperatieve vennootschap (WVV)',                            'Société coopérative (CSA)',                                        'commercial'),
  ('716', 'Coöperatieve vennootschap van publiek recht (WVV)',          'Société coopérative de droit public (CSA)',                        'public'),
  ('721', 'Vennootschap zonder rechtspersoonlijkheid',                   'Société sans personnalité juridique',                              'other'),
  ('722', 'Tijdelijke vereniging',                                       'Association momentanée',                                           'other'),
  ('723', 'Kostendelende vereniging',                                    'Association de frais',                                             'other'),
  ('724', 'Vakbond',                                                     'Syndicat',                                                         'nonprofit'),
  ('790', 'Diversen zonder rechtspersoonlijkheid',                       'Divers sans personnalité juridique',                               'other'),
  ('999', 'Ongekende rechtsvorm',                                        'Forme inconnue',                                                   'other')
ON CONFLICT (code) DO UPDATE
  SET label_nl = EXCLUDED.label_nl,
      label_fr = EXCLUDED.label_fr,
      category = EXCLUDED.category;

-- -----------------------------------------------------------------------
-- 6. Legal-form synonyms (bidirectional). Used only at query-expansion
--    time; indexing preserves original-form display fidelity.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS legal_form_synonyms (
  form       text PRIMARY KEY,    -- what the user types (lowercased)
  canonical  text NOT NULL        -- canonical bucket key
);

INSERT INTO legal_form_synonyms (form, canonical) VALUES
  ('nv',     'nv'),   ('sa',     'nv'),
  ('bv',     'bv'),   ('sprl',   'bv'),   ('srl',    'bv'),   ('bvba',   'bv'),
  ('cvba',   'cv'),   ('scrl',   'cv'),   ('cv',     'cv'),
  ('vof',    'vof'),  ('snc',    'vof'),
  ('comm.v', 'commv'),('comm v', 'commv'),('scs',    'commv'),('scomm',  'commv'),
  ('vzw',    'vzw'),  ('asbl',   'vzw'),
  ('ivzw',   'ivzw'), ('aisbl',  'ivzw'),
  ('se',     'se'),
  ('gmbh',   'gmbh'), ('ag',     'ag'),   ('kg',     'kg'),   ('ohg',    'ohg'),
  ('ug',     'ug'),
  ('ltd',    'ltd'),  ('plc',    'plc'),  ('llp',    'llp'),
  ('inc',    'inc'),  ('corp',   'corp'), ('llc',    'llc'),
  ('sas',    'sas'),  ('sarl',   'sarl'), ('eurl',   'sarl'),
  ('spa',    'spa')
ON CONFLICT (form) DO UPDATE SET canonical = EXCLUDED.canonical;

-- -----------------------------------------------------------------------
-- 7. Company popularity (ranking signal), refreshed nightly.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS company_popularity (
  enterprise_number  text PRIMARY KEY,
  click_count        integer NOT NULL DEFAULT 0,
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_company_popularity_count
  ON company_popularity (click_count DESC);

COMMIT;

-- -----------------------------------------------------------------------
-- Phase 1 — company_info: drop old text column, recreate as GENERATED,
-- add trigram + prefix indexes.
-- -----------------------------------------------------------------------
BEGIN;
DROP INDEX IF EXISTS idx_ci_name_trgm;
ALTER TABLE company_info DROP COLUMN IF EXISTS name_normalized;
ALTER TABLE company_info
  ADD COLUMN name_normalized text
    GENERATED ALWAYS AS (search_normalize(name)) STORED;
CREATE INDEX IF NOT EXISTS idx_ci_name_norm_trgm
  ON company_info USING GIN (name_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_ci_name_norm_prefix
  ON company_info (name_normalized text_pattern_ops);
COMMIT;

ANALYZE company_info;

-- -----------------------------------------------------------------------
-- Phase 2 — administrator: three generated columns + three GIN indexes.
-- Longest-running phase on prod (~3-6 min). If interrupted, re-running
-- is safe: `ADD COLUMN IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`.
-- -----------------------------------------------------------------------
BEGIN;
ALTER TABLE administrator
  ADD COLUMN IF NOT EXISTS name_normalized text
    GENERATED ALWAYS AS (search_normalize(name)) STORED;
ALTER TABLE administrator
  ADD COLUMN IF NOT EXISTS name_reversed text
    GENERATED ALWAYS AS (search_name_reversed(name)) STORED;
ALTER TABLE administrator
  ADD COLUMN IF NOT EXISTS name_phonetic text
    GENERATED ALWAYS AS (search_phonetic_key(name)) STORED;
CREATE INDEX IF NOT EXISTS idx_admin_name_norm_trgm
  ON administrator USING GIN (name_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_admin_name_rev_trgm
  ON administrator USING GIN (name_reversed gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_admin_name_phon_trgm
  ON administrator USING GIN (name_phonetic gin_trgm_ops);
COMMIT;

ANALYZE administrator;

-- -----------------------------------------------------------------------
-- Phase 3 — shareholder (1-3 min).
-- -----------------------------------------------------------------------
BEGIN;
ALTER TABLE shareholder
  ADD COLUMN IF NOT EXISTS name_normalized text
    GENERATED ALWAYS AS (search_normalize(name)) STORED;
ALTER TABLE shareholder
  ADD COLUMN IF NOT EXISTS name_reversed text
    GENERATED ALWAYS AS (search_name_reversed(name)) STORED;
ALTER TABLE shareholder
  ADD COLUMN IF NOT EXISTS name_phonetic text
    GENERATED ALWAYS AS (search_phonetic_key(name)) STORED;
CREATE INDEX IF NOT EXISTS idx_sh_name_norm_trgm
  ON shareholder USING GIN (name_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sh_name_rev_trgm
  ON shareholder USING GIN (name_reversed gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sh_name_phon_trgm
  ON shareholder USING GIN (name_phonetic gin_trgm_ops);
COMMIT;

ANALYZE shareholder;

-- -----------------------------------------------------------------------
-- Phase 4 — staatsblad_event (30-90 s).
-- -----------------------------------------------------------------------
BEGIN;
ALTER TABLE staatsblad_event
  ADD COLUMN IF NOT EXISTS person_name_normalized text
    GENERATED ALWAYS AS (search_normalize(person_name)) STORED;
ALTER TABLE staatsblad_event
  ADD COLUMN IF NOT EXISTS person_name_reversed text
    GENERATED ALWAYS AS (search_name_reversed(person_name)) STORED;
ALTER TABLE staatsblad_event
  ADD COLUMN IF NOT EXISTS person_name_phonetic text
    GENERATED ALWAYS AS (search_phonetic_key(person_name)) STORED;
CREATE INDEX IF NOT EXISTS idx_sb_person_norm_trgm
  ON staatsblad_event USING GIN (person_name_normalized gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sb_person_rev_trgm
  ON staatsblad_event USING GIN (person_name_reversed gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sb_person_phon_trgm
  ON staatsblad_event USING GIN (person_name_phonetic gin_trgm_ops);
COMMIT;

ANALYZE staatsblad_event;

-- -----------------------------------------------------------------------
-- Phase 5 — denomination (3-7 min — the widest rewrite).
-- -----------------------------------------------------------------------
BEGIN;
ALTER TABLE denomination
  ADD COLUMN IF NOT EXISTS denomination_normalized text
    GENERATED ALWAYS AS (search_normalize(denomination)) STORED;
CREATE INDEX IF NOT EXISTS idx_denom_norm_trgm
  ON denomination USING GIN (denomination_normalized gin_trgm_ops);
COMMIT;

ANALYZE denomination;
