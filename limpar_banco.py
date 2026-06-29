import os
import psycopg2

def limpar_banco():
    print("=" * 55)
    print("   LIMPEZA TOTAL DO BANCO DE DADOS - Maria's Home Service")
    print("=" * 55)
    print()
    print("ATENCAO: Esta operacao ira apagar TODOS os registros de:")
    print("   - Agendamentos")
    print("   - Clientes")
    print("   - Prestadoras")
    print()
    print("   Os IDs serao reiniciados do zero (comeca do 1).")
    print()

    confirmacao = input("Digite CONFIRMAR para prosseguir: ").strip()
    if confirmacao != "CONFIRMAR":
        print("\nOperacao cancelada.")
        return

    # Obtém a URL de conexão
    pg_url = os.environ.get("DATABASE_URL", "")
    if not pg_url:
        print("\nInsira a URL de conexao EXTERNA do PostgreSQL no Render")
        print("(Render > seu servico de BD > Info > External Database URL):")
        pg_url = input("> ").strip()

    if not pg_url:
        print("\nURL nao fornecida. Abortando.")
        return

    pg_url = pg_url.replace("postgres://", "postgresql://", 1)

    print("\nConectando ao banco de dados...")
    try:
        conn = psycopg2.connect(pg_url)
        cur = conn.cursor()
    except Exception as e:
        print(f"\nErro ao conectar: {e}")
        return

    try:
        print("Apagando todos os registros e reiniciando sequencias...")

        # TRUNCATE com RESTART IDENTITY reinicia o auto-increment (SERIAL) do 1
        # CASCADE remove também as FKs dependentes automaticamente
        cur.execute("""
            TRUNCATE TABLE agendamentos, clientes, prestadoras
            RESTART IDENTITY CASCADE;
        """)
        conn.commit()

        # Confirma que ficou vazio
        cur.execute("SELECT COUNT(*) FROM clientes")
        c = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM prestadoras")
        p = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM agendamentos")
        a = cur.fetchone()[0]

        print()
        print("LIMPEZA CONCLUIDA COM SUCESSO!")
        print(f"   Clientes restantes    : {c}")
        print(f"   Prestadoras restantes : {p}")
        print(f"   Agendamentos restantes: {a}")
        print()
        print("IDs reiniciados do 1. O sistema esta pronto para uso real.")

    except Exception as e:
        conn.rollback()
        print(f"\nErro durante a limpeza: {e}")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    limpar_banco()
