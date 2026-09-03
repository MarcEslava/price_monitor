"""
DAG esquemàtic (il·lustratiu, no pensat per executar-se tal qual) que mostra
com encaixaria el projecte price_monitor dins d'Airflow.

Patró: extract (spiders, un per competidor, en paral·lel)
    -> transform (neteja/normalització dels items crus)
    -> load (upsert a Postgres, taula d'històric)
    -> detect (comparar amb l'últim preu conegut)
    -> notify (només si hi ha canvis)

Notes de disseny:
- Els spiders NOMÉS extreuen i escriuen dades crues (JSON Lines) a un
  directori "staging". Ja no fan la detecció de canvis ells mateixos
  (a diferència del pipelines.py actual, que ho barreja tot en un sol pas).
  Separar-ho fa que cada peça es pugui reintentar/monitoritzar per separat
  des d'Airflow.
- BashOperator crida "scrapy crawl" directament, com si fos terminal.
  És la manera més senzilla d'integrar Scrapy amb Airflow sense haver de
  gestionar el reactor de Twisted dins del propi procés d'Airflow (que
  dona problemes si es criden crawls Scrapy diverses vegades via
  PythonOperator dins el mateix worker).
- Per producció real, la alternativa més robusta és desplegar els spiders
  a Scrapyd (dimoni separat) i que Airflow només faci crides HTTP per
  llançar/consultar els crawls -- així el cicle de vida del crawl no
  depèn del cicle de vida del worker d'Airflow.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator

SPIDERS = ["competitor_acme", "competitor_beta", "competitor_gamma"]  # un per site
STAGING_DIR = "/opt/airflow/data/staging/{{ ds }}"

default_args = {
    "owner": "price_monitor",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="price_monitor_daily",
    description="Recull preus de la competencia, detecta canvis i alerta",
    schedule="0 6 * * *",  # cada dia a les 6:00
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["scraping", "prices"],
) as dag:

    start = EmptyOperator(task_id="start")

    # --- EXTRACT: una tasca per spider, corren en paral·lel ---
    extract_tasks = []
    for spider_name in SPIDERS:
        task = BashOperator(
            task_id=f"extract_{spider_name}",
            bash_command=(
                f"cd /opt/airflow/price_monitor && "
                f"scrapy crawl {spider_name} "
                f"-o {STAGING_DIR}/{spider_name}.jsonl:jsonlines"
            ),
        )
        extract_tasks.append(task)

    # --- TRANSFORM + LOAD: normalitza tots els fitxers crus i fa upsert a Postgres ---
    def transform_and_load(**context):
        """
        Llegeix tots els .jsonl del directori de staging del dia, neteja
        preus/monedes/noms, i fa upsert a la taula 'price_history' de
        Postgres. (Implementació real fora d'abast d'aquest esquema.)
        """
        ds = context["ds"]
        staging_dir = f"/opt/airflow/data/staging/{ds}"
        # ... llegir jsonl, normalitzar, escriure a Postgres via hook ...
        print(f"Normalitzant i carregant items de {staging_dir}")

    load_task = PythonOperator(
        task_id="transform_and_load",
        python_callable=transform_and_load,
    )

    # --- DETECT: compara el preu nou amb l'últim registrat per producte ---
    def detect_price_changes(**context):
        """
        Consulta Postgres: per cada producte, compara l'observació d'avui
        amb l'anterior. Escriu els canvis a la taula 'price_alerts' i els
        deixa disponibles via XCom perquè la tasca de notificació decideixi
        si cal enviar alguna cosa.
        """
        # ... query SQL de comparació ...
        alerts_found = 0  # exemple
        context["ti"].xcom_push(key="alerts_found", value=alerts_found)

    detect_task = PythonOperator(
        task_id="detect_price_changes",
        python_callable=detect_price_changes,
    )

    # --- NOTIFY: només si detect_price_changes ha trobat alguna cosa ---
    def notify_if_changes(**context):
        alerts_found = context["ti"].xcom_pull(
            task_ids="detect_price_changes", key="alerts_found"
        )
        if alerts_found:
            # ... enviar email / missatge a Slack / etc ...
            print(f"Enviant alerta: {alerts_found} canvis de preu detectats")
        else:
            print("Sense canvis de preu avui, no cal notificar")

    notify_task = PythonOperator(
        task_id="notify_if_changes",
        python_callable=notify_if_changes,
    )

    end = EmptyOperator(task_id="end")

    # --- Dependències del DAG ---
    start >> extract_tasks >> load_task >> detect_task >> notify_task >> end
