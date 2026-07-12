"""
Envía un HTML como mail vía Gmail SMTP usando una App Password.

La contraseña de aplicación se lee de la variable de entorno GMAIL_APP_PASSWORD
(nunca se pasa por línea de comandos ni se guarda en el repo).

Uso:
    GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx" python3 enviar_mail.py \
        --from joacog500@gmail.com \
        --to joacog500@gmail.com,daniel@laordenweb.com \
        --subject "Asunto del mail" \
        --html-file reportes/output/ultimo_reporte_semanal.html
"""
import argparse
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_email", required=True)
    parser.add_argument("--to", required=True, help="destinatarios separados por coma")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--html-file", required=True)
    args = parser.parse_args()

    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not app_password:
        print("Falta la variable de entorno GMAIL_APP_PASSWORD", file=sys.stderr)
        sys.exit(1)

    with open(args.html_file, "r", encoding="utf-8") as f:
        html = f.read()

    destinatarios = [d.strip() for d in args.to.split(",") if d.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = args.subject
    msg["From"] = args.from_email
    msg["To"] = ", ".join(destinatarios)
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(args.from_email, app_password)
        server.sendmail(args.from_email, destinatarios, msg.as_string())

    print(f"Mail enviado a: {', '.join(destinatarios)}")


if __name__ == "__main__":
    main()
