User units are generated with absolute paths for the current checkout:

```sh
.venv/bin/python scripts/install_services.py --web --enable
```

Omit `--enable` to review files first, or use `--output /tmp/units` for validation.
No Docker/root service is used. See `docs/INTRANET.zh-CN.md` for environment,
isolation, loopback access, data preparation and recovery boundaries.
