# ZFM ICMS Copilot — Flask + Google Sheets


## 1) Planilha Google (estrutura sugerida)
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