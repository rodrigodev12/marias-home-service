import os
import psycopg2
import psycopg2.extras
from datetime import date, datetime
from zoneinfo import ZoneInfo
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, g, session

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'marias_home_service_secret_key_2024')

# ---------------------------------------------------------------------------
# CREDENCIAIS DO ADMINISTRADOR
# ---------------------------------------------------------------------------
ADMIN_USER     = 'admin'
ADMIN_PASSWORD = 'Maria@2025'


def login_required(f):
    """Decorator que redireciona para /login se o admin não estiver autenticado."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Acesso restrito. Faça login para continuar.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# DATABASE HELPERS (PostgreSQL via psycopg2)
# ---------------------------------------------------------------------------

# Render publica DATABASE_URL como postgres://, mas psycopg2 exige postgresql://
_raw_url    = os.environ.get('DATABASE_URL', '')
DATABASE_URL = _raw_url.replace('postgres://', 'postgresql://', 1)


class _DBWrapper:
    """Faz psycopg2 se comportar como sqlite3 para minimizar mudanças no código."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, args=()):
        # Converte placeholders ? (sqlite) → %s (postgres)
        pg_sql = sql.replace('?', '%s')
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(pg_sql, args if args else ())
        return cur

    def commit(self):   self._conn.commit()
    def rollback(self): self._conn.rollback()
    def close(self):    self._conn.close()


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        conn = psycopg2.connect(DATABASE_URL)
        db = g._database = _DBWrapper(conn)
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        if exception:
            db.rollback()
        db.close()


def _col_exists(db, table, column):
    """Verifica existência de coluna via information_schema (PostgreSQL)."""
    cur = db.execute(
        'SELECT 1 FROM information_schema.columns WHERE table_name = ? AND column_name = ?',
        (table, column)
    )
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# UTILITÁRIO DE DATA
# ---------------------------------------------------------------------------

def formatar_data_para_br(data_str):
    if not data_str:
        return ""
    data_str = data_str.strip()

    if '/' in data_str:
        parts = data_str.split('/')
        if len(parts) == 3:
            d, m, y = parts[0], parts[1], parts[2]
            if len(y) > 4:
                y = y[-4:]
            return f"{d.zfill(2)}/{m.zfill(2)}/{y}"
        return data_str

    if '-' in data_str:
        parts = data_str.split('-')
        if len(parts) == 3:
            if len(parts[0]) >= 4:
                ano, mes, dia = parts[0], parts[1], parts[2]
                if ano == '60629' and mes == '02' and dia == '20':
                    return '29/06/2026'
                if len(ano) > 4:
                    ano = ano[-4:]
                return f"{dia.zfill(2)}/{mes.zfill(2)}/{ano}"
            elif len(parts[2]) >= 4:
                dia, mes, ano = parts[0], parts[1], parts[2]
                if len(ano) > 4:
                    ano = ano[-4:]
                return f"{dia.zfill(2)}/{mes.zfill(2)}/{ano}"

    return data_str


# ---------------------------------------------------------------------------
# INICIALIZAÇÃO DO BANCO DE DADOS
# ---------------------------------------------------------------------------

def init_db():
    with app.app_context():
        db = get_db()

        # ── Cria tabelas se não existirem ──
        db.execute('''
            CREATE TABLE IF NOT EXISTS clientes (
                id          SERIAL PRIMARY KEY,
                nome        TEXT   NOT NULL,
                telefone    TEXT,
                email       TEXT,
                endereco    TEXT,
                observacoes TEXT
            )
        ''')

        db.execute('''
            CREATE TABLE IF NOT EXISTS prestadoras (
                id                  SERIAL PRIMARY KEY,
                nome                TEXT   NOT NULL,
                telefone            TEXT,
                especialidades      TEXT,
                disponibilidade     TEXT,
                bairro              TEXT,
                referencias         TEXT,
                preferencia_horario TEXT
            )
        ''')

        db.execute('''
            CREATE TABLE IF NOT EXISTS agendamentos (
                id               SERIAL  PRIMARY KEY,
                id_cliente       INTEGER NOT NULL REFERENCES clientes(id),
                id_prestadora    INTEGER REFERENCES prestadoras(id),
                data             TEXT    NOT NULL,
                horario          TEXT    NOT NULL,
                status           TEXT    DEFAULT 'Pendente',
                servico_agendado TEXT,
                observacoes      TEXT,
                valor_cliente    NUMERIC(10,2) DEFAULT 0,
                valor_prestadora NUMERIC(10,2) DEFAULT 0,
                lucro_empresa    NUMERIC(10,2) DEFAULT 0
            )
        ''')

        # ── Migrações seguras: adiciona colunas que possam estar faltando ──
        for col, ctype in [
            ('servico_agendado', 'TEXT'),
            ('observacoes', 'TEXT'),
            ('valor_cliente',    'NUMERIC(10,2) DEFAULT 0'),
            ('valor_prestadora', 'NUMERIC(10,2) DEFAULT 0'),
            ('lucro_empresa',    'NUMERIC(10,2) DEFAULT 0'),
        ]:
            if not _col_exists(db, 'agendamentos', col):
                db.execute(f'ALTER TABLE agendamentos ADD COLUMN {col} {ctype}')

        for col, ctype in [
            ('bairro', 'TEXT'), ('referencias', 'TEXT'), ('preferencia_horario', 'TEXT')
        ]:
            if not _col_exists(db, 'prestadoras', col):
                db.execute(f'ALTER TABLE prestadoras ADD COLUMN {col} {ctype}')

        db.commit()

        # ── Normaliza datas para DD/MM/AAAA ──
        rows = db.execute('SELECT id, data FROM agendamentos').fetchall()
        for row in rows:
            new_date = formatar_data_para_br(row['data'])
            if new_date != row['data']:
                db.execute('UPDATE agendamentos SET data = ? WHERE id = ?',
                           (new_date, row['id']))
        db.commit()


# Auto-inicialização ao ser importado pelo Gunicorn
if DATABASE_URL:
    try:
        init_db()
    except Exception as _e:
        print(f'[init_db] Aviso: {_e}')


# ---------------------------------------------------------------------------
# FAVICON (Evita erro 404 e lentidão no carregamento)
# ---------------------------------------------------------------------------

@app.route('/favicon.ico')
def favicon():
    return '', 204


# ---------------------------------------------------------------------------
# LOGIN / LOGOUT
# ---------------------------------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('admin_logged_in'):
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip()
        senha   = request.form.get('senha', '')
        if usuario == ADMIN_USER and senha == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            flash('Bem-vindo ao painel, Administrador!', 'success')
            return redirect(url_for('dashboard'))
        flash('Usuário ou senha incorretos. Tente novamente.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Você saiu do sistema com segurança.', 'info')
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------------

@app.route('/')
@login_required
def dashboard():
    db = get_db()

    _agora   = datetime.now(ZoneInfo('America/Sao_Paulo'))
    hoje_br  = _agora.strftime('%d/%m/%Y')
    hoje_iso = _agora.date().isoformat()

    total_clientes     = db.execute('SELECT COUNT(*) AS total FROM clientes').fetchone()['total']
    total_prestadoras  = db.execute('SELECT COUNT(*) AS total FROM prestadoras').fetchone()['total']
    total_agendamentos = db.execute('SELECT COUNT(*) AS total FROM agendamentos').fetchone()['total']

    # ── Resumo financeiro ──
    fin = db.execute('''
        SELECT
            COALESCE(SUM(valor_cliente),    0) AS faturamento_total,
            COALESCE(SUM(valor_prestadora), 0) AS total_repasse,
            COALESCE(SUM(lucro_empresa),    0) AS lucro_liquido
        FROM agendamentos
        WHERE status IN (%s, %s)
    ''', ('Confirmado', 'Concluído')).fetchone()
    faturamento_total = float(fin['faturamento_total'] or 0)
    total_repasse     = float(fin['total_repasse']     or 0)
    lucro_liquido     = float(fin['lucro_liquido']     or 0)

    agendamentos_hoje = db.execute('''
        SELECT a.id, c.nome AS cliente,
               COALESCE(p.nome, '— A definir') AS prestadora,
               a.id_prestadora,
               a.data, a.horario, a.status, a.servico_agendado, a.observacoes
        FROM   agendamentos a
        JOIN   clientes     c ON c.id = a.id_cliente
        LEFT JOIN prestadoras p ON p.id = a.id_prestadora
        WHERE  a.data = ?
        ORDER  BY a.horario
    ''', (hoje_br,)).fetchall()

    proximos_agendamentos = db.execute('''
        SELECT a.id, c.nome AS cliente,
               COALESCE(p.nome, '— A definir') AS prestadora,
               a.id_prestadora,
               a.data, a.horario, a.status, a.servico_agendado, a.observacoes
        FROM   agendamentos a
        JOIN   clientes     c ON c.id = a.id_cliente
        LEFT JOIN prestadoras p ON p.id = a.id_prestadora
        WHERE  (SUBSTR(a.data, 7, 4) || '-' || SUBSTR(a.data, 4, 2) || '-' || SUBSTR(a.data, 1, 2)) >= ?
        ORDER  BY SUBSTR(a.data, 7, 4) || '-' || SUBSTR(a.data, 4, 2) || '-' || SUBSTR(a.data, 1, 2) ASC,
                  a.horario ASC
        LIMIT  10
    ''', (hoje_iso,)).fetchall()

    prestadoras = db.execute('SELECT id, nome FROM prestadoras ORDER BY nome').fetchall()

    return render_template('dashboard.html',
                           total_clientes=total_clientes,
                           total_prestadoras=total_prestadoras,
                           total_agendamentos=total_agendamentos,
                           faturamento_total=faturamento_total,
                           total_repasse=total_repasse,
                           lucro_liquido=lucro_liquido,
                           agendamentos_hoje=agendamentos_hoje,
                           proximos_agendamentos=proximos_agendamentos,
                           prestadoras=prestadoras,
                           hoje=hoje_br)


# ---------------------------------------------------------------------------
# CLIENTES
# ---------------------------------------------------------------------------

@app.route('/clientes')
@login_required
def listar_clientes():
    db = get_db()
    clientes = db.execute('SELECT * FROM clientes ORDER BY nome').fetchall()
    return render_template('clientes.html', clientes=clientes)


@app.route('/clientes/novo', methods=['GET', 'POST'])
@login_required
def novo_cliente():
    if request.method == 'POST':
        nome        = request.form['nome'].strip()
        telefone    = request.form.get('telefone', '').strip()
        email       = request.form.get('email', '').strip()
        endereco    = request.form.get('endereco', '').strip()
        observacoes = request.form.get('observacoes', '').strip()

        if not nome:
            flash('O nome do cliente é obrigatório.', 'danger')
            return redirect(url_for('novo_cliente'))

        db = get_db()
        db.execute(
            'INSERT INTO clientes (nome, telefone, email, endereco, observacoes) VALUES (?, ?, ?, ?, ?)',
            (nome, telefone, email, endereco, observacoes)
        )
        db.commit()
        flash(f'Cliente "{nome}" cadastrado com sucesso!', 'success')
        return redirect(url_for('listar_clientes'))

    return render_template('novo_cliente.html')


@app.route('/clientes/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    db = get_db()
    cliente = db.execute('SELECT * FROM clientes WHERE id = ?', (id,)).fetchone()
    if not cliente:
        flash('Cliente não encontrado.', 'danger')
        return redirect(url_for('listar_clientes'))

    if request.method == 'POST':
        nome        = request.form['nome'].strip()
        telefone    = request.form.get('telefone', '').strip()
        email       = request.form.get('email', '').strip()
        endereco    = request.form.get('endereco', '').strip()
        observacoes = request.form.get('observacoes', '').strip()

        if not nome:
            flash('O nome do cliente é obrigatório.', 'danger')
            return redirect(url_for('editar_cliente', id=id))

        db.execute(
            'UPDATE clientes SET nome=?, telefone=?, email=?, endereco=?, observacoes=? WHERE id=?',
            (nome, telefone, email, endereco, observacoes, id)
        )
        db.commit()
        flash(f'Cliente "{nome}" atualizado com sucesso!', 'success')
        return redirect(url_for('listar_clientes'))

    return render_template('editar_cliente.html', cliente=cliente)


@app.route('/clientes/<int:id>/excluir', methods=['GET', 'POST'])
@login_required
def excluir_cliente(id):
    # Acesso direto via GET não é permitido → redireciona sem executar nada
    if request.method == 'GET':
        flash('Ação inválida. Use o botão de exclusão na lista de clientes.', 'warning')
        return redirect(url_for('listar_clientes'))

    db = get_db()
    cliente = db.execute('SELECT nome FROM clientes WHERE id = ?', (id,)).fetchone()
    if cliente:
        try:
            db.execute('DELETE FROM clientes WHERE id = ?', (id,))
            db.commit()
            flash(f'Cliente "{cliente["nome"]}" excluído com sucesso.', 'warning')
        except Exception:
            db.rollback()
            flash(
                f'Não foi possível excluir o cliente "{cliente["nome"]}" pois ele possui '
                'agendamentos vinculados. Exclua os agendamentos primeiro.',
                'danger'
            )
    else:
        flash('Cliente não encontrado.', 'danger')
    return redirect(url_for('listar_clientes'))


# ---------------------------------------------------------------------------
# PRESTADORAS
# ---------------------------------------------------------------------------

@app.route('/prestadoras')
@login_required
def listar_prestadoras():
    db = get_db()
    prestadoras = db.execute('SELECT * FROM prestadoras ORDER BY nome').fetchall()
    return render_template('prestadoras.html', prestadoras=prestadoras)


@app.route('/prestadoras/nova', methods=['GET', 'POST'])
@login_required
def nova_prestadora():
    especialidades_opcoes = ['Diarista', 'Passadeira', 'Babá', 'Cozinheira']

    if request.method == 'POST':
        nome            = request.form['nome'].strip()
        telefone        = request.form.get('telefone', '').strip()
        especialidades  = request.form.getlist('especialidades')
        disponibilidade = request.form.get('disponibilidade', '').strip()

        if not nome:
            flash('O nome da prestadora é obrigatório.', 'danger')
            return redirect(url_for('nova_prestadora'))

        esp_str = ', '.join(especialidades)
        db = get_db()
        db.execute(
            'INSERT INTO prestadoras (nome, telefone, especialidades, disponibilidade) VALUES (?, ?, ?, ?)',
            (nome, telefone, esp_str, disponibilidade)
        )
        db.commit()
        flash(f'Prestadora "{nome}" cadastrada com sucesso!', 'success')
        return redirect(url_for('listar_prestadoras'))

    return render_template('nova_prestadora.html', especialidades_opcoes=especialidades_opcoes)


@app.route('/prestadoras/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar_prestadora(id):
    db = get_db()
    prestadora = db.execute('SELECT * FROM prestadoras WHERE id = ?', (id,)).fetchone()
    if not prestadora:
        flash('Prestadora não encontrada.', 'danger')
        return redirect(url_for('listar_prestadoras'))

    especialidades_opcoes = ['Diarista', 'Passadeira', 'Babá', 'Cozinheira']
    especialidades_atuais = [e.strip() for e in (prestadora['especialidades'] or '').split(',') if e.strip()]

    if request.method == 'POST':
        nome            = request.form['nome'].strip()
        telefone        = request.form.get('telefone', '').strip()
        especialidades  = request.form.getlist('especialidades')
        disponibilidade = request.form.get('disponibilidade', '').strip()

        if not nome:
            flash('O nome da prestadora é obrigatório.', 'danger')
            return redirect(url_for('editar_prestadora', id=id))

        esp_str = ', '.join(especialidades)
        db.execute(
            'UPDATE prestadoras SET nome=?, telefone=?, especialidades=?, disponibilidade=? WHERE id=?',
            (nome, telefone, esp_str, disponibilidade, id)
        )
        db.commit()
        flash(f'Prestadora "{nome}" atualizada com sucesso!', 'success')
        return redirect(url_for('listar_prestadoras'))

    return render_template('editar_prestadora.html',
                           prestadora=prestadora,
                           especialidades_opcoes=especialidades_opcoes,
                           especialidades_atuais=especialidades_atuais)


@app.route('/prestadoras/<int:id>/excluir', methods=['POST'])
@login_required
def excluir_prestadora(id):
    db = get_db()
    prestadora = db.execute('SELECT nome FROM prestadoras WHERE id = ?', (id,)).fetchone()
    if prestadora:
        db.execute('DELETE FROM prestadoras WHERE id = ?', (id,))
        db.commit()
        flash(f'Prestadora "{prestadora["nome"]}" excluída.', 'warning')
    return redirect(url_for('listar_prestadoras'))


# ---------------------------------------------------------------------------
# AGENDAMENTOS
# ---------------------------------------------------------------------------

@app.route('/agendamentos')
@login_required
def listar_agendamentos():
    db = get_db()
    agendamentos = db.execute('''
        SELECT a.id, c.nome AS cliente,
               COALESCE(p.nome, '— A definir') AS prestadora,
               a.data, a.horario, a.status, a.servico_agendado, a.observacoes
        FROM   agendamentos a
        JOIN   clientes     c ON c.id = a.id_cliente
        LEFT JOIN prestadoras p ON p.id = a.id_prestadora
        ORDER  BY SUBSTR(a.data, 7, 4) || '-' || SUBSTR(a.data, 4, 2) || '-' || SUBSTR(a.data, 1, 2) DESC,
                  a.horario DESC
    ''').fetchall()
    return render_template('agendamentos.html', agendamentos=agendamentos)


@app.route('/agendamentos/novo', methods=['GET', 'POST'])
@login_required
def novo_agendamento():
    db = get_db()
    clientes    = db.execute('SELECT id, nome FROM clientes ORDER BY nome').fetchall()
    prestadoras = db.execute('SELECT id, nome FROM prestadoras ORDER BY nome').fetchall()

    if request.method == 'POST':
        id_cliente       = request.form.get('id_cliente')
        id_prestadora    = request.form.get('id_prestadora')
        data             = formatar_data_para_br(request.form.get('data', '').strip())
        horario          = request.form.get('horario', '').strip()
        status           = request.form.get('status', 'Pendente')
        servico_agendado = request.form.get('servico_agendado', '').strip()

        if not all([id_cliente, id_prestadora, data, horario, servico_agendado]):
            flash('Preencha todos os campos obrigatórios, incluindo o Serviço Solicitado.', 'danger')
            return render_template('novo_agendamento.html',
                                   clientes=clientes, prestadoras=prestadoras)

        db.execute(
            'INSERT INTO agendamentos (id_cliente, id_prestadora, data, horario, status, servico_agendado)'
            ' VALUES (?, ?, ?, ?, ?, ?)',
            (id_cliente, id_prestadora, data, horario, status, servico_agendado)
        )
        db.commit()
        flash('Agendamento criado com sucesso!', 'success')
        return redirect(url_for('listar_agendamentos'))

    return render_template('novo_agendamento.html', clientes=clientes, prestadoras=prestadoras)


@app.route('/agendamentos/<int:id>/status', methods=['POST'])
@login_required
def atualizar_status(id):
    novo_status = request.form.get('status')
    db = get_db()
    db.execute('UPDATE agendamentos SET status = ? WHERE id = ?', (novo_status, id))
    db.commit()
    flash('Status do agendamento atualizado!', 'success')
    return redirect(url_for('listar_agendamentos'))


@app.route('/agendamentos/<int:id>/excluir', methods=['POST'])
@login_required
def excluir_agendamento(id):
    db = get_db()
    db.execute('DELETE FROM agendamentos WHERE id = ?', (id,))
    db.commit()
    flash('Agendamento excluído.', 'warning')
    return redirect(url_for('listar_agendamentos'))


@app.route('/atribuir_prestadora', methods=['POST'])
@login_required
def atribuir_prestadora():
    id_agendamento   = request.form.get('id_agendamento')
    id_prestadora    = request.form.get('id_prestadora')
    valor_cliente_s  = request.form.get('valor_cliente', '0').replace(',', '.').strip()
    valor_prest_s    = request.form.get('valor_prestadora', '0').replace(',', '.').strip()

    if not id_agendamento or not id_prestadora:
        flash('Erro ao atribuir prestadora.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        valor_cliente_f  = float(valor_cliente_s)  if valor_cliente_s  else 0.0
        valor_prest_f    = float(valor_prest_s)     if valor_prest_s    else 0.0
    except ValueError:
        valor_cliente_f = 0.0
        valor_prest_f   = 0.0

    lucro_f = valor_cliente_f - valor_prest_f

    db = get_db()
    db.execute('''
        UPDATE agendamentos
        SET id_prestadora = ?, status = 'Confirmado',
            valor_cliente = ?, valor_prestadora = ?, lucro_empresa = ?
        WHERE id = ?
    ''', (id_prestadora, valor_cliente_f, valor_prest_f, lucro_f, id_agendamento))
    db.commit()
    flash('Prestadora atribuída com sucesso! O status foi alterado para Confirmado.', 'success')
    return redirect(url_for('dashboard'))


# ---------------------------------------------------------------------------
# FLUXO DE CAIXA / FINANCEIRO
# ---------------------------------------------------------------------------

@app.route('/financeiro')
@login_required
def financeiro():
    db = get_db()

    # Totais gerais (somente Confirmado / Concluído)
    totais = db.execute('''
        SELECT
            COALESCE(SUM(valor_cliente),    0) AS faturamento_total,
            COALESCE(SUM(valor_prestadora), 0) AS total_repasse,
            COALESCE(SUM(lucro_empresa),    0) AS lucro_liquido
        FROM agendamentos
        WHERE status IN (%s, %s)
    ''', ('Confirmado', 'Concluído')).fetchone()

    # Histórico completo de agendamentos com valores financeiros
    historico = db.execute('''
        SELECT a.id, a.data, a.status,
               c.nome AS cliente,
               COALESCE(p.nome, '— A definir') AS prestadora,
               a.servico_agendado,
               COALESCE(a.valor_cliente,    0) AS valor_cliente,
               COALESCE(a.valor_prestadora, 0) AS valor_prestadora,
               COALESCE(a.lucro_empresa,    0) AS lucro_empresa
        FROM   agendamentos a
        JOIN   clientes     c ON c.id = a.id_cliente
        LEFT JOIN prestadoras p ON p.id = a.id_prestadora
        ORDER  BY SUBSTR(a.data, 7, 4) || '-' || SUBSTR(a.data, 4, 2) || '-' || SUBSTR(a.data, 1, 2) DESC,
                  a.id DESC
    ''').fetchall()

    return render_template('financeiro.html',
                           totais=totais,
                           historico=historico)


# ---------------------------------------------------------------------------
# SOLICITAÇÃO PÚBLICA DE AGENDAMENTO (CLIENTES)
# ---------------------------------------------------------------------------

SERVICOS_OPCOES = ['Diarista', 'Passadeira', 'Babá', 'Cozinheira']
PERIODOS_OPCOES = ['Manhã (07h às 12h)', 'Tarde (13h às 18h)', 'Integral']


@app.route('/agendamento_cliente', methods=['GET', 'POST'])
def agendamento_cliente_publico():
    if request.method == 'POST':
        nome     = request.form.get('nome', '').strip()
        telefone = request.form.get('telefone', '').strip()
        email    = request.form.get('email', '').strip()
        endereco = request.form.get('endereco', '').strip()
        bairro   = request.form.get('bairro', '').strip()

        servico     = request.form.get('servico', '').strip()
        data        = formatar_data_para_br(request.form.get('data', '').strip())
        periodo     = request.form.get('periodo', '').strip()
        observacoes = request.form.get('observacoes', '').strip()

        # Captura o valor calculado em tempo real pelo cliente
        try:
            valor_total = float(request.form.get('valor_total', '0').replace(',', '.').strip())
        except (ValueError, AttributeError):
            valor_total = 0.0

        if not all([nome, telefone, servico, data, periodo]):
            flash('Preencha todos os campos obrigatórios.', 'danger')
            return render_template('agendamento_cliente.html',
                                   servicos_opcoes=SERVICOS_OPCOES,
                                   periodos_opcoes=PERIODOS_OPCOES)

        db = get_db()

        # Reutiliza cliente se já cadastrado, caso contrário insere
        if email:
            cliente_existente = db.execute(
                'SELECT id FROM clientes WHERE telefone = ? OR email = ?',
                (telefone, email)
            ).fetchone()
        else:
            cliente_existente = db.execute(
                'SELECT id FROM clientes WHERE telefone = ?', (telefone,)
            ).fetchone()

        if cliente_existente:
            id_cliente = cliente_existente['id']
            db.execute(
                'UPDATE clientes SET nome=?, email=?, endereco=? WHERE id=?',
                (nome, email, f'{endereco}, {bairro}'.strip(', '), id_cliente)
            )
        else:
            # RETURNING id é PostgreSQL — evita lastrowid que não existe no psycopg2
            row = db.execute(
                'INSERT INTO clientes (nome, telefone, email, endereco) VALUES (?, ?, ?, ?) RETURNING id',
                (nome, telefone, email, f'{endereco}, {bairro}'.strip(', '))
            ).fetchone()
            id_cliente = row['id']

        db.execute(
            '''INSERT INTO agendamentos
               (id_cliente, id_prestadora, data, horario, status, servico_agendado, observacoes, valor_cliente)
               VALUES (?, NULL, ?, ?, 'Pendente', ?, ?, ?)''',
            (id_cliente, data, periodo, servico, observacoes, valor_total)
        )
        db.commit()
        return redirect(url_for('agendamento_cliente_sucesso'))

    return render_template('agendamento_cliente.html',
                           servicos_opcoes=SERVICOS_OPCOES,
                           periodos_opcoes=PERIODOS_OPCOES)


@app.route('/agendamento_cliente/sucesso')
def agendamento_cliente_sucesso():
    return render_template('agendamento_cliente_sucesso.html')


# ---------------------------------------------------------------------------
# CADASTRO PÚBLICO DE PRESTADORAS
# ---------------------------------------------------------------------------

ESPECIALIDADES_OPCOES = ['Diarista', 'Passadeira', 'Babá', 'Cozinheira']

DISPONIBILIDADE_OPCOES = [
    'Segunda-feira', 'Terça-feira', 'Quarta-feira',
    'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo'
]

HORARIOS_OPCOES = [
    'Manhã (07h às 12h)',
    'Tarde (13h às 18h)',
    'Noite (18h às 22h)',
    'Integral'
]


@app.route('/cadastro_prestadora', methods=['GET', 'POST'])
def cadastro_prestadora_publico():
    if request.method == 'POST':
        nome                = request.form.get('nome', '').strip()
        telefone            = request.form.get('telefone', '').strip()
        bairro              = request.form.get('bairro', '').strip()
        especialidades      = request.form.getlist('especialidades')
        disponibilidade     = request.form.getlist('disponibilidade')
        referencias         = request.form.get('referencias', 'Não').strip()
        preferencia_horario = request.form.get('preferencia_horario', '').strip()

        if not nome or not telefone:
            flash('Nome e Telefone são obrigatórios.', 'danger')
            return render_template('cadastro_prestadora.html',
                                   especialidades_opcoes=ESPECIALIDADES_OPCOES,
                                   disponibilidade_opcoes=DISPONIBILIDADE_OPCOES,
                                   horarios_opcoes=HORARIOS_OPCOES)

        if not preferencia_horario:
            flash('Selecione o Período de Preferência.', 'danger')
            return render_template('cadastro_prestadora.html',
                                   especialidades_opcoes=ESPECIALIDADES_OPCOES,
                                   disponibilidade_opcoes=DISPONIBILIDADE_OPCOES,
                                   horarios_opcoes=HORARIOS_OPCOES)

        esp_str  = ', '.join(especialidades)
        disp_str = ', '.join(disponibilidade)

        db = get_db()
        db.execute(
            '''INSERT INTO prestadoras
               (nome, telefone, especialidades, disponibilidade, bairro, referencias, preferencia_horario)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (nome, telefone, esp_str, disp_str, bairro, referencias, preferencia_horario)
        )
        db.commit()
        return redirect(url_for('cadastro_prestadora_sucesso'))

    return render_template('cadastro_prestadora.html',
                           especialidades_opcoes=ESPECIALIDADES_OPCOES,
                           disponibilidade_opcoes=DISPONIBILIDADE_OPCOES,
                           horarios_opcoes=HORARIOS_OPCOES)


@app.route('/cadastro_prestadora/sucesso')
def cadastro_prestadora_sucesso():
    return render_template('cadastro_prestadora_sucesso.html')


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if DATABASE_URL:
        init_db()
    port  = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
