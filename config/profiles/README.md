Profile layout:

- `config.gb.ini`: GB profile, keeps the curated GB annotation memory.
- `config.iec.ini`: IEC profile, reuses the same graph structure and parameter skeleton, but starts from empty annotation memory.
- `config.dlt.ini`: DLT profile, same as IEC profile; current aliases already map `温升试验` to `连续电流试验`.

Activation:

- Run `tools/activate_profile.sh gb`
- Run `tools/activate_profile.sh iec`
- Run `tools/activate_profile.sh dlt`

What activation changes:

- Copies the selected config into `config.ini`
- Copies the selected annotation memory into `lightrag/config/annotation_memory.json`
- Updates `.env` with `WORKING_DIR=./data/rag_storage_<profile>`

Result:

- GB/IEC/DLT use different `rag_storage`
- IEC/DLT no longer read GB annotation memory by default
- All three profiles still share the same report/test/parameter skeleton unless you later choose to diverge them
