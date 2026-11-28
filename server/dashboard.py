import argparse
import logging
import signal
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, abort, cli, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from common.filtros import validar_filtro_assinatura
from server.state import TIMEOUT_AGENTE_PADRAO, EstadoCentral
from server.subscriber import (
    ARQUIVO_LOG_PADRAO,
    FILTRO_PADRAO,
    HOST_PADRAO,
    PORTA_PADRAO,
    MonitorCentral,
    _porta_valida,
    configurar_logs,
)

WEB_HOST_PADRAO: str = "0.0.0.0"
WEB_PORTA_PADRAO: int = 8080
TIMEOUT_AGENTE_MINIMO: float = 2.0
EVENTOS_NA_API: int = 30

RAIZ_PROJETO = Path(__file__).resolve().parent.parent

logger = logging.getLogger("monitor.dashboard")

# Textos dos erros HTTP que podem chegar à tela (o navegador mostra o campo "erro" como veio)
MENSAGENS_HTTP: Dict[int, str] = {
    400: "Requisição inválida.",
    404: "Rota não encontrada.",
    405: "Método não permitido para esta rota.",
    413: "Corpo da requisição grande demais.",
    500: "Erro interno do servidor do dashboard.",
}


def _eh_rota_api(caminho: str) -> bool:
    return caminho == "/api" or caminho.startswith("/api/")


def _corpo_json() -> Dict[str, Any]:
    # force=True: aceita o JSON mesmo sem o cabeçalho Content-Type (curl, scripts de teste);
    # silent=True: corpo ausente ou malformado vira None em vez de uma exceção
    dados = request.get_json(force=True, silent=True)
    if not isinstance(dados, dict):
        raise ValueError("O corpo da requisição deve ser um objeto JSON.")
    return dados


def _erro_400(exc: ValueError):
    return jsonify({"ok": False, "erro": str(exc)}), 400


def criar_app(monitor: MonitorCentral, pasta_web: str = "web") -> Flask:
    # Pasta relativa é procurada na raiz do projeto, para o comando funcionar de qualquer diretório
    pasta = Path(pasta_web)
    if not pasta.is_absolute():
        pasta = RAIZ_PROJETO / pasta

    # static_folder=None: os arquivos de web/ são servidos pela rota abaixo, que sabe
    # devolver JSON (e não HTML) quando o caminho começa com /api/
    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    # --- API ---

    @app.get("/api/estado")
    def api_estado():
        return jsonify(
            {
                "servidor_hora": datetime.now().astimezone().isoformat(timespec="seconds"),
                "broker": monitor.estado_broker(),
                "filtro": monitor.filtro,
                "timeout_agente": monitor.estado.timeout_agente,
                "contadores": monitor.contadores(),
                "maquinas": monitor.estado.snapshot_dashboard(),
                "eventos": monitor.eventos_recentes(EVENTOS_NA_API),
            }
        )

    @app.get("/api/historico")
    def api_historico():
        return jsonify(monitor.estado.historico_todas())

    # Nas duas rotas abaixo, ValueError é "dado inválido digitado pela pessoa" (o texto já vem
    # em português do monitor) e vira 400. Qualquer outra exceção é bug e cai no 500.
    @app.post("/api/filtro")
    def api_filtro():
        try:
            dados = _corpo_json()
            if "filtro" not in dados:
                raise ValueError("Informe o campo 'filtro', por exemplo 'monitoramento/+/cpu'.")
            monitor.alterar_filtro(dados["filtro"])
        except ValueError as exc:
            return _erro_400(exc)
        return jsonify({"ok": True, "filtro": monitor.filtro})

    @app.post("/api/broker")
    def api_broker():
        try:
            dados = _corpo_json()
            if "host" not in dados or "porta" not in dados:
                raise ValueError("Informe os campos 'host' e 'porta' do broker.")
            monitor.reconectar(dados["host"], dados["porta"])
        except ValueError as exc:
            return _erro_400(exc)
        return jsonify({"ok": True, "host": monitor.host, "porta": monitor.porta})

    @app.after_request
    def sem_cache_na_api(resposta):
        # O navegador consulta a API a cada 2 s: nada disso pode vir de cache
        if _eh_rota_api(request.path):
            resposta.headers["Cache-Control"] = "no-store"
        return resposta

    # --- Páginas e arquivos de web/ ---

    def servir_arquivo(caminho: str):
        resposta = send_from_directory(pasta, caminho)
        resposta.headers["Cache-Control"] = "no-store"
        return resposta

    @app.get("/")
    def pagina_inicial():
        return servir_arquivo("index.html")

    @app.route("/<path:caminho>", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
    def arquivo_web(caminho: str):
        # Rota "pega-tudo": qualquer coisa sob /api/ que não casou com as rotas acima é 404
        # (inclusive para POST, que de outro modo viraria um 405 enganoso)
        if _eh_rota_api(request.path):
            # Rota que existe, mas não para este método (ex.: POST /api/estado), é 405
            existentes = {r.rule for r in app.url_map.iter_rules() if r.rule.startswith("/api/")}
            abort(405 if request.path in existentes else 404)
        if request.method not in ("GET", "HEAD"):
            abort(405)
        return servir_arquivo(caminho)

    # --- Erros: em /api/* a resposta é sempre JSON, nunca HTML ---

    @app.errorhandler(Exception)
    def erro_generico(exc: Exception):
        api = _eh_rota_api(request.path)

        if isinstance(exc, HTTPException):
            if not api:
                return exc
            codigo = exc.code or 500
            erro = MENSAGENS_HTTP.get(codigo, f"Erro na requisição (código {codigo}).")
            if codigo == 404:
                erro = f"Rota não encontrada: {request.path}"
            elif codigo == 405:
                erro = f"Método {request.method} não permitido em {request.path}"
        else:
            # Linha curta para o painel de eventos e o arquivo de log; o traceback vai para o console
            logger.error("Erro interno em %s %s: %r", request.method, request.path, exc)
            app.logger.exception("Erro não tratado em %s %s", request.method, request.path)
            if not api:
                return "Erro interno do servidor.", 500
            codigo = 500
            erro = MENSAGENS_HTTP[500]

        return jsonify({"ok": False, "erro": erro}), codigo

    return app


def _timeout_valido(texto: str) -> float:
    try:
        valor = float(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"timeout inválido: '{texto}'")
    if valor < TIMEOUT_AGENTE_MINIMO:
        raise argparse.ArgumentTypeError(
            f"o timeout deve ser de pelo menos {TIMEOUT_AGENTE_MINIMO:g} segundos"
        )
    return valor


def ler_argumentos(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m server.dashboard",
        description="Dashboard web do monitor central (abra no navegador de qualquer máquina da rede).",
    )
    parser.add_argument(
        "--host", default=HOST_PADRAO,
        help=f"endereço inicial do broker MQTT; dá para trocar na tela (padrão: {HOST_PADRAO})",
    )
    parser.add_argument(
        "--porta", type=_porta_valida, default=PORTA_PADRAO,
        help=f"porta inicial do broker MQTT; dá para trocar na tela (padrão: {PORTA_PADRAO})",
    )
    parser.add_argument(
        "--web-host", default=WEB_HOST_PADRAO,
        help=f"endereço em que o dashboard escuta; 0.0.0.0 aceita outras máquinas (padrão: {WEB_HOST_PADRAO})",
    )
    parser.add_argument(
        "--web-porta", type=_porta_valida, default=WEB_PORTA_PADRAO,
        help=f"porta do dashboard (padrão: {WEB_PORTA_PADRAO})",
    )
    parser.add_argument(
        "--filtro", default=FILTRO_PADRAO,
        help=f"filtro de assinatura inicial; dá para trocar na tela (padrão: {FILTRO_PADRAO})",
    )
    parser.add_argument(
        "--timeout-agente", type=_timeout_valido, default=TIMEOUT_AGENTE_PADRAO,
        help=(
            "segundos sem dados até a máquina ser considerada indisponível "
            f"(padrão: {TIMEOUT_AGENTE_PADRAO:g}; mínimo: {TIMEOUT_AGENTE_MINIMO:g})"
        ),
    )
    parser.add_argument(
        "--log", default=ARQUIVO_LOG_PADRAO, metavar="ARQUIVO",
        help=f"arquivo de log com conexões e mensagens recebidas (padrão: {ARQUIVO_LOG_PADRAO})",
    )

    args = parser.parse_args(argv)

    validacao = validar_filtro_assinatura(args.filtro)
    if not validacao.valido:
        parser.error(f"--filtro inválido: {validacao.erro}")
    return args


def _ip_da_rede() -> Optional[str]:
    # IP que esta máquina usa para sair para a rede. O "connect" de UDP não envia nada:
    # só faz o sistema escolher a interface.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
    except OSError:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            return None
    return None if ip.startswith("127.") or ip == "0.0.0.0" else ip


def _urls_de_acesso(web_host: str, web_porta: int) -> List[str]:
    if web_host in ("0.0.0.0", "::", ""):
        urls = [f"http://localhost:{web_porta}"]
        ip = _ip_da_rede()
        if ip:
            urls.append(f"http://{ip}:{web_porta}")
        return urls
    return [f"http://{web_host}:{web_porta}"]


def main(argv: Optional[List[str]] = None) -> int:
    args = ler_argumentos(argv)
    eventos = configurar_logs(args.log)

    # O navegador consulta a API a cada poucos segundos; sem isto o terminal
    # ficaria cheio de linhas "GET /api/estado 200"
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    cli.show_server_banner = lambda *_args, **_kwargs: None  # tira o " * Serving Flask app"

    estado = EstadoCentral(timeout_agente=args.timeout_agente)
    monitor = MonitorCentral(
        host=args.host,
        porta=args.porta,
        filtro=args.filtro,
        estado=estado,
        eventos=eventos,
    )
    app = criar_app(monitor)

    # Sem isto o SIGTERM encerraria o processo sem passar pelo finally
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    monitor.iniciar_em_segundo_plano()
    try:
        print(f"Broker MQTT: {args.host}:{args.porta} | filtro: {args.filtro} | timeout: {args.timeout_agente:g} s")
        print("Dashboard disponível em:")
        for url in _urls_de_acesso(args.web_host, args.web_porta):
            print(f"  {url}")
        print("Ctrl+C para encerrar.")
        sys.stdout.flush()

        app.run(host=args.web_host, port=args.web_porta, threaded=True, debug=False, use_reloader=False)
    except OSError as exc:
        print(f"Não foi possível abrir o dashboard em {args.web_host}:{args.web_porta}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    finally:
        monitor.encerrar()
        print("\nDashboard encerrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
