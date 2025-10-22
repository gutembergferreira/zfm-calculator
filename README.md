# ZFM ICMS Copilot — Flask + Banco de Dados

> **Atualização:** As matrizes utilizadas pelo motor de cálculo (aliquotas, MVA, ST, etc.) agora são carregadas a partir das tabelas do banco de dados (`aliquotas`, `mva`, `multiplicadores`, `st_regras`, `sources`, `sources_log`, `config`, `creditos_presumidos`). A antiga integração com Google Sheets foi removida.


## 1) Planilha Google (estrutura sugerida)
> **Histórico:** Esta seção descreve a antiga estrutura em Google Sheets e pode ser utilizada como referência para popular as tabelas do banco de dados com os mesmos campos.
Crie uma planilha com **estas abas** e **headers**:


### `aliquotas`
| UF | TIPO | UF_DEST | ALIQ |
|----|------|---------|------|
| AM | INTERNA | - | 0.20 |
| SP | INTERESTADUAL | AM | 0.12 |


> Observação: para linhas "INTERNA" use `UF_DEST` como `-` ou deixe vazio.


### `mva`
| NCM | SEGMENTO | MVA |
|-----|----------|-----|
| 32081010 | Tintas/Vernizes | 35.00 |


### `multiplicadores`
| NCM | REGIAO | MULT |
|-----|--------|------|
| 32081010 | ZFM_SSE | 19.47 |


> Se preferir, substitua `REGIAO` por colunas específicas (N/N, S/SE, ZF_NN, ZF_SSE) e filtre pela que usar.


### `creditos_presumidos`
| NCM | REGRA | PERC |
|-----|-------|------|
| 32081010 | tinta_credito_presumido | 10.00 |


*(ainda não aplicado no `calc.py`; reservado para próxima iteração)*


### `excecoes`
| NCM | CFOP | CST | REGRA |
|-----|------|-----|-------|
| 32081010 | 6.401 | 10 | usar_mva=0;usar_mult=1 |


### `config`
| CHAVE | VALOR |
|-------|-------|
| usar_multiplicador_default | 1 |


> **Compartilhe a planilha** com o e‑mail da **Service Account** (permissão de leitura).


## 2) Credenciais Google
- Crie um **Projeto** no Google Cloud → **APIs & Services** → habilite **Google Sheets API** e **Drive API**.
- Em **Credentials**, crie **Service Account**, adicione uma **Key (JSON)** → salve como `service_account.json` na raiz do projeto.
- Compartilhe a planilha com o e‑mail da Service Account.


## 3) Execução (local)
```bash
python -m venv .venv
source .venv/bin/activate # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env # edite SPREADSHEET_ID e caminhos
flask run
```


## 4) Próximos passos (iterar rápido)
- **Comparativo SEFAZ**: criar aba `sefaz_rules` ou endpoint para importar cálculos oficiais (quando possível) e gerar quadro comparativo.
- **Crédito presumido**: aplicar no `calc.py` conforme NCM/CFOP/CST (regra parametrizada).
- **Template PDF** com Jinja2+WeasyPrint para layout mais rico (ou manter ReportLab simples).
- **Logs** em outra aba (`logs`) com data, CNPJ emitente/destinatário (se extraído), totais e hash da NF.
- **Autenticação** básica (um usuário admin) e página de histórico (cache em disco) — sem banco de dados, seguindo a proposta de usar apenas Sheets/arquivos.


## 5) Observações
- O motor de cálculo está **didático** e isolado em `calc.py`. Ajuste as fórmulas conforme suas tabelas ZFM (MVA vs multiplicador) e regras de encerramento.
- `xml_parser.py` faz um **rateio simples do frete** por item. Se quiser, altere para proporcional ao valor do item.
- Para evitar quebra com planilhas vazias, preencha **ao menos uma linha** por aba com valores padrão.
## Novas funcionalidades (2025-09-27)

- Pastas por usuário para uploads XML: `UPLOAD_FOLDER/user_<id>/YYYY/MM`.
- Modelos novos: `UserFile`, `NFESummary`, `AuditLog` em `oraculoicms_app/models/file.py`.
- Plano com limites de armazenamento: campos adicionados em `Plan` (`max_files`, `max_storage_mb`, `max_monthly_files`, `max_monthly_storage_mb`).
- Blueprint `files`: rotas `/meus-arquivos`, `/upload-xml`, `/ver-xml/<id>`, `/deletar-xml/<id>`, `/parse-xml/<id>`, `/relatorios/nfe`.
- Templates: `templates/files.html` (gestão de XMLs) e `templates/relatorio_geral.html` (relatório geral).

### Migração do banco

Se você usa Flask-Migrate:
```
flask db migrate -m "user files & summaries"
flask db upgrade
```

Para ambiente DEV rápido:
```
flask init-db
```

> Garanta que `User` tenha relacionamento `plan` (ex.: `user.plan_id -> Plan.id`). Se não houver, inclua a coluna `plan_id` em `users` e ajuste conforme seu fluxo de assinatura.


Rodar Testes Unitários:
```
pytest --cov=oraculoicms_app --cov=xml_parser --cov-report=term-missing --cov-report=html
```


