bind = "0.0.0.0:8000"        # im Container; nach außen nur 127.0.0.1 (compose.yaml)
workers = 2                  # LocMem-Cache (Login-Drosselung, Zähler) gilt je Worker
worker_class = "sync"
timeout = 120
accesslog = "-"
errorlog = "-"
loglevel = "info"
