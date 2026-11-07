// Read-only replay of an explicitly exported synthetic run; never calls the RSI API.
(() => {
  const el = (id) => document.getElementById(`rsi-${id}`);
  const node = (tag, text) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; };
  const percent = (x) => `${(x * 100).toFixed(1)}%`;
  const labels = { baseline: '開始時の指示文', accepted: '候補に残す', not_better: '改善と認めず', rejected: '却下', unmeasured: '測定できず' };
  const phases = ['開始時を測定', '候補生成・検査・評価', '別データで最終確認', '人に推薦'];
  let data, position = -1, timer = null, loading = false;
  const finished = () => data && position >= data.candidates.length + 1;
  const pause = () => { clearInterval(timer); timer = null; el('play').textContent = position === -1 ? 'テストを再生' : finished() ? '再生済み' : '再生を続ける'; };
  const block = (title, text) => { const d = node('details'); d.append(node('summary', title), node('pre', text)); return d; };

  function candidate(c) {
    const detail = el('detail'); detail.hidden = false; detail.replaceChildren();
    detail.append(node('h2', `${c.id}：${labels[c.status]}`));
    detail.append(node('p', `親：${c.parent || 'なし'} ／ 点数：${c.score == null ? '未測定' : percent(c.score)} ／ 必須ルール違反：${c.violations}件`));
    if (c.repeats) detail.append(node('p', `繰り返し測定：${c.repeats.map(percent).join(' → ')}`));
    if (c.reasons.length) detail.append(node('p', c.reasons.join('。')));
    if (c.rationale) detail.append(block('改善役の分析・変更理由（AI）', c.rationale));
    if (c.diff) { const diff = block('親からの変更（− 削除 ／ ＋ 追加）', c.diff); diff.open = true; detail.append(diff); }
    detail.append(block('指示文の全文', c.prompt));
    if (c.examples.length) {
      detail.append(node('h3', 'この候補でも残った失敗の例'));
      detail.append(node('p', '評価後の記録の抜粋です。実際に改善役へ渡された例の一覧ではありません。'));
      c.examples.forEach((e) => {
        const title = { missed_gap: '見逃し', false_alarm: '誤った指摘', guardrail: 'ルール違反' }[e.failure.kind];
        detail.append(block(`${title}：${e.failure.pred_claim || e.failure.gold_claim || e.failure.case_id}`, JSON.stringify(e, null, 2)));
      });
    }
  }

  function render() {
    const count = data.candidates.length;
    const phase = position < 0 ? -1 : position === 0 ? 0 : position < count ? 1 : position === count ? 2 : 3;
    el('flow').replaceChildren(...phases.map((title, i) => {
      const li = node('li', `${i < phase ? '✓ ' : ''}${title}`);
      if (i === phase) li.setAttribute('aria-current', 'step'); return li;
    }));
    el('candidates').replaceChildren();
    data.candidates.slice(0, Math.min(position + 1, count)).forEach((c) => {
      const row = node('tr'), cell = node('td'), b = node('button', `${c.id} ← ${c.parent || '開始'}`);
      b.type = 'button'; b.onclick = () => { pause(); candidate(c); }; cell.append(b);
      row.append(cell, node('td', c.score == null ? '未測定' : percent(c.score)), node('td', labels[c.status])); el('candidates').append(row);
    });
    el('next').disabled = position >= count + 1;
    el('reset').disabled = position < 0;
    el('play').disabled = position >= count + 1;
    if (position < 0) { el('detail').hidden = true; el('status').textContent = '準備完了。「テストを再生」または「次のステップ」で開始します。'; return; }
    if (position < count) {
      const c = data.candidates[position]; candidate(c);
      el('status').textContent = `ステップ ${position + 1}/${count + 2}：${c.id} を評価 → ${labels[c.status]}`;
    } else {
      const d = el('detail'); d.hidden = false; d.replaceChildren();
      if (position === count) {
        d.append(node('h2', '探索に使わなかった別データで比較'));
        Object.entries(data.heldout).forEach(([id, score]) => d.append(node('p', `${id}：${percent(score)}`)));
        d.append(node('p', '最終確認の失敗例は、書き直し役に渡しません。候補が開始時より下がらず、必須ルールを守れば推薦します。'));
        el('status').textContent = '最終確認：改善用データへの合わせすぎを確認';
      } else {
        const start = data.candidates[0].id, base = data.heldout[start], best = data.heldout[data.best];
        const verdict = best == null || base == null ? '別データでの点数が記録にありません'
          : `別データで開始時 ${percent(base)} → ${data.best} ${percent(best)}。開始時より${best >= base ? '下がりませんでした' : '下がりました'}`;
        d.append(node('h2', `${data.best} を推薦`), node('p', `この記録の判定：${verdict}。人が差分を確認し、採用するか決めます。`));
        d.append(node('p', '再生が完了しました。本番の指示文は変更していません。'));
        el('status').textContent = '完了：改善候補の推薦まで再生しました'; pause();
      }
    }
  }
  function next() { if (data && position < data.candidates.length + 1) { position++; render(); } }
  el('next').onclick = () => { pause(); next(); };
  el('reset').onclick = () => { position = -1; pause(); render(); };
  el('play').onclick = () => {
    if (timer) { pause(); return; }
    el('play').textContent = '一時停止'; next();
    if (position < data.candidates.length + 1) timer = setInterval(next, 3000);
  };
  window.loadRsiTest = async () => {
    if (data || loading) return;
    loading = true; el('error').textContent = '';
    try {
      const response = await fetch('rsi-test-assets/rsi-demo.json');
      if (!response.ok) throw new Error('記録を読み込めませんでした');
      data = await response.json();
      if (!data.synthetic || data.decision !== 'recommended' || !data.candidates?.length) throw new Error('対応していない記録です');
      el('meta').textContent = `記録：${data.run_id} ／ 対象：${data.target} ／ 各${data.meta.repeats}回測定 ／ 開始時のぶれ：${(data.noise * 100).toFixed(1)}ポイント`;
      el('play').disabled = false; render();
    } catch (error) { data = null; el('error').textContent = `${error.message}。RSIテストのタブを押して再試行してください。`; }
    finally { loading = false; }
  };
})();
