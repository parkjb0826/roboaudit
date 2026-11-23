"""출력: HTML 성적표 / JSON 결과 / clean_index.json / review_index.json /
배지 SVG / (옵션) 마크다운 성적표."""
import json
from pathlib import Path

from jinja2 import Template

_GRADE_COLORS = {"A": "#2e7d32", "B": "#558b2f", "C": "#e0a800",
                 "D": "#e07b00", "F": "#c62828"}


def render_badge(result: dict) -> str:
    """점수·등급 배지 SVG (shields.io 스타일, 외부 서비스 없이 자체 생성)."""
    score, grade = result["score"], result["grade"]
    label, value = "roboaudit", f"{score} · {grade}"
    color = _GRADE_COLORS.get(grade, "#5a6a85")
    lw = 10 + int(6.6 * len(label))
    vw = 10 + int(6.6 * len(value))
    w = lw + vw
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" '
        f'role="img" aria-label="{label}: {value}">'
        f"<title>{label}: {value}</title>"
        f'<rect width="{lw}" height="20" fill="#555"/>'
        f'<rect x="{lw}" width="{vw}" height="20" fill="{color}"/>'
        f'<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" '
        f'font-size="11">'
        f'<text x="{lw / 2:.0f}" y="14" text-anchor="middle">{label}</text>'
        f'<text x="{lw + vw / 2:.0f}" y="14" text-anchor="middle">'
        f"{value}</text></g></svg>")


def _md_cell(x):
    return str(x).replace("|", "\\|").replace("\n", " ")


def render_markdown(result: dict) -> str:
    """마크다운 성적표 (0.3.2): PR·이슈·데이터셋 카드에 붙이는 용도."""
    s = result["summary"]
    lines = [
        f"# 🩺 RoboAudit 성적표 — {s['dataset']}",
        "",
        f"**점수: {result['score']}/100 · 등급 {result['grade']}** "
        f"(총 감점 {result['total_deduction']}점 · 발견 "
        f"{len(result['findings'])}건)",
        "",
        f"- 형식: LeRobot {s['format']} · 에피소드 {s['total_episodes']}개"
        f" · FPS {s['fps']} · 로봇 {s['robot_type']}",
        f"- 제외 {len(result['excluded_episodes'])}개 · 보류 "
        f"{len(result['review_episodes'])}개 · 깨끗함 "
        f"{len(result['clean_episodes'])}개",
    ]
    if s.get("repo_id"):
        lines.append(f"- Hub: [{s['repo_id']}]"
                     f"(https://huggingface.co/datasets/{s['repo_id']})")
    if result.get("incomplete_audit"):
        lines.append("- ⚠ **불완전한 감사** — 일부 검사가 전체 범위를 "
                     "검사하지 못했습니다.")
    dg = result.get("diagnostics", {}).get("timestamp_grid") or {}
    if dg.get("message"):
        lines.append(f"- ⏱ {dg['message']}")
    if result.get("top_factors"):
        lines += ["", "## 감점 이유 Top "
                  f"{len(result['top_factors'])}", ""]
        for i, t in enumerate(result["top_factors"], 1):
            lines.append(f"{i}. `{t['check']}` {t['name']} — "
                         f"{t['findings']}건, -{t['deduction']}점 "
                         f"(감점의 {t['share_pct']}%)")
    lines += ["", f"## 검사 {len(result['checks'])}종 결과", "",
              "| 검사 | 항목 | 심각도 | 결과 | 발견 | 감점 |",
              "|---|---|---|---|---|---|"]
    for c in result["checks"]:
        lines.append(f"| `{c['check']}` | {_md_cell(c['name'])} | "
                     f"{c['severity']} | {c['status']} | {c['findings']}건 "
                     f"| {c['deduction']}점 |")
    if result.get("task_scores"):
        lines += ["", "## 과제별 점수", "",
                  "| 과제 | 에피소드 | 발견 | 감점 | 점수 | 등급 |",
                  "|---|---|---|---|---|---|"]
        for t in result["task_scores"]:
            lines.append(f"| {_md_cell(t['task'])} | {t['episodes']} "
                         f"| {t['findings']} | {t['deduction']} "
                         f"| {t['score']} | {t['grade']} |")
        lines.append("")
        lines.append(f"데이터셋 단위 발견의 감점 "
                     f"{result.get('dataset_level_deduction', 0)}점은 "
                     "어느 과제에도 넣지 않았습니다.")
    if result.get("review_shortlist"):
        lines += ["", "## 먼저 볼 에피소드 (보류 단축목록)", "",
                  "| 순위 | 에피소드 | 걸린 검사 | jerk p95 | 최대 스텝 "
                  "| 정지 비율 | 최종 자세 거리(σ) |",
                  "|---|---|---|---|---|---|---|"]
        for it in result["review_shortlist"]:
            m = it.get("metrics") or {}
            ep_cell = str(it["episode_index"])
            if it.get("visualizer_url"):
                ep_cell = f"[{it['episode_index']}]" \
                          f"({it['visualizer_url']})"
            idle = ("-" if m.get("idle_ratio") is None
                    else f"{100 * m['idle_ratio']:.0f}%")
            lines.append(
                f"| {it['rank']} | {ep_cell} | "
                f"{', '.join(it['checks'])} | "
                f"{m.get('jerk_p95', '-')} | {m.get('max_step', '-')} | "
                f"{idle} | {m.get('final_pose_distance', '-')} |")
    dc = result.get("delete_commands") or {}
    if dc.get("excluded_command"):
        lines += ["", "제외 에피소드 삭제 명령 (RoboAudit는 실행하지 "
                  "않습니다 — 확인 후 직접 실행하세요):", "",
                  "```bash", dc["excluded_command"], "```"]
    if result["findings"]:
        lines += ["", "## 에피소드별 결함 목록", "",
                  "| 검사 | 에피소드 | 심각도 | 처분 | 내용 |",
                  "|---|---|---|---|---|"]
        for f in result["findings"]:
            ep = ("전체" if f["episode_index"] is None
                  else f["episode_index"])
            disp = ("-" if f["episode_index"] is None else
                    result["dispositions"].get(str(f["episode_index"]), "-"))
            lines.append(f"| `{f['check']}` | {ep} | {f['severity']} "
                         f"| {disp} | {_md_cell(f['detail'])} |")
    if result.get("notices"):
        lines += ["", "## 고지 · 해석 범위", ""]
        lines += [f"- {n}" for n in result["notices"]]
    man = result["manifest"]
    lines += ["", "---",
              f"RoboAudit v{man['tool']['version']} · 규칙 "
              f"{man['rules_version']} · 입력 지문 "
              f"{man['input_fingerprint']['value'][:16]}… · "
              "원본 데이터는 읽기만 했습니다"]
    return "\n".join(lines) + "\n"

# autoescape 필수: 데이터셋 이름·과제 문자열·detail 등 데이터 유래 문자열이
# HTML 태그로 해석되지 않게 한다 (추가 검토 smoke test에서 원문 주입 확인 후 수정).
_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>RoboAudit 성적표 - {{ r.summary.dataset }}</title>
<style>
  body { font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; background:#f4f6fb; color:#1c2434; margin:0; padding:24px 16px 48px; }
  .wrap { max-width: 900px; margin: 0 auto; }
  .card { background:#fff; border-radius:16px; padding:24px; margin-bottom:20px; box-shadow:0 2px 10px rgba(30,50,90,.08); }
  h1 { font-size:24px; margin:0 0 4px; }
  .sub { color:#5a6a85; font-size:14px; }
  .scorebox { display:flex; align-items:center; gap:28px; }
  .score { font-size:64px; font-weight:800; line-height:1; }
  .grade { font-size:40px; font-weight:800; padding:10px 22px; border-radius:14px; color:#fff; }
  .gA { background:#2e7d32; } .gB { background:#558b2f; } .gC { background:#e0a800; }
  .gD { background:#e07b00; } .gF { background:#c62828; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { border:1px solid #dde3ef; padding:7px 10px; text-align:left; vertical-align:top; }
  th { background:#f0f3fa; }
  .fail { color:#c62828; font-weight:700; } .pass { color:#2e7d32; font-weight:700; }
  .sev-critical { color:#c62828; font-weight:700; } .sev-warning { color:#e07b00; font-weight:700; } .sev-info { color:#5a6a85; font-weight:700; }
  .meta { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin-top:14px; }
  .meta div { background:#f7f9fd; border-radius:10px; padding:10px 12px; font-size:13px; }
  .meta b { display:block; font-size:15px; margin-top:2px; }
  code { background:#eef1f7; padding:1px 5px; border-radius:5px; font-size:12px; }
  .warn-banner { background:#fff3e0; border:2px solid #e07b00; color:#7a4a00; border-radius:12px; padding:14px 18px; margin-bottom:20px; font-weight:700; }
  .top3 { background:#eef4ff; border-radius:12px; padding:14px 18px; margin-top:16px; font-size:15px; line-height:1.7; }
  .disp-exclude { color:#c62828; font-weight:700; } .disp-review { color:#e07b00; font-weight:700; }
  .rs-partial, .rs-error { color:#c62828; font-weight:700; } .rs-complete { color:#2e7d32; } .rs-not_applicable { color:#5a6a85; }
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <h1>🩺 RoboAudit 데이터셋 성적표</h1>
    <div class="sub">{{ r.summary.dataset }} · LeRobot {{ r.summary.format }} · 로봇 {{ r.summary.robot_type }}</div>
    <div class="meta">
      <div>에피소드<b>{{ r.summary.total_episodes }}개</b></div>
      <div>총 프레임(메타)<b>{{ r.summary.total_frames_meta }}</b></div>
      <div>FPS<b>{{ r.summary.fps }}</b></div>
      <div>지시문 종류<b>{{ r.summary.total_tasks }}종</b></div>
      <div>제외 에피소드<b>{{ r.excluded_episodes | length }}개</b></div>
      <div>보류 에피소드<b>{{ r.review_episodes | length }}개</b></div>
      <div>깨끗한 에피소드<b>{{ r.clean_episodes | length }}개</b></div>
      <div>감사 카메라<b>{{ r.summary.video_keys | join(', ') }}</b></div>
    </div>
    {% if r.diagnostics and r.diagnostics.timestamp_grid %}
    <div style="margin-top:12px; font-size:14px; color:#44506a;">⏱ {{ r.diagnostics.timestamp_grid.message }}</div>
    {% endif %}
  </div>

  {% if r.incomplete_audit %}
  <div class="warn-banner">⚠ 불완전한 감사 — 일부 검사가 전체 범위를 검사하지 못했습니다.
  아래 검사표의 실행 상태(부분/오류)와 범위를 확인하세요. 검사하지 못한 부분은 정상으로 간주되지 않습니다.</div>
  {% endif %}

  {% if r.summary.sample_frames %}
  <div class="warn-banner">⚠ 표본 모드 결과 — 에피소드당 최대 {{ r.summary.sample_frames }}프레임 표본으로 계산한 근사치입니다.
  표본에서는 프레임 간격이 벌어져 V1 정지 판정이 전수보다 엄격해질 수 있고 경계 구간의 정지를 놓칠 수 있습니다. 최종 판정은 전수 재실행을 권장합니다.</div>
  {% endif %}

  <div class="card">
    <div class="scorebox">
      <div class="score">{{ r.score }}<span style="font-size:22px; color:#5a6a85;">/100</span></div>
      <div class="grade g{{ r.grade }}">{{ r.grade }}</div>
      <div style="font-size:14px; color:#44506a; line-height:1.6;">
        총 감점 <b>{{ r.total_deduction }}점</b> (치명 -10 · 경고 -3 · 참고 -1)<br>
        발견된 문제 <b>{{ r.findings | length }}건</b> · 검사 오류 {{ r.errors | length }}건
        {% if r.summary.sample_frames %}<br>표본 모드: 에피소드당 최대 {{ r.summary.sample_frames }}프레임{% endif %}
      </div>
    </div>
    {% if r.top_factors %}
    <div class="top3">
      <b>감점 이유 Top {{ r.top_factors | length }}</b><br>
      {% for t in r.top_factors %}
      {{ loop.index }}. <code>{{ t.check }}</code> {{ t.name }} — {{ t.findings }}건, -{{ t.deduction }}점 (감점의 {{ t.share_pct }}%)<br>
      {% endfor %}
    </div>
    {% endif %}
  </div>

  <div class="card">
    <h2 style="margin-top:0; font-size:19px;">검사 {{ r.checks | length }}종 결과</h2>
    <table>
      <tr><th>검사</th><th>항목</th><th>심각도</th><th>결과</th><th>실행 상태</th><th>검사 범위</th><th>발견</th><th>감점</th></tr>
      {% for c in r.checks %}
      <tr>
        <td><code>{{ c.check }}</code></td><td>{{ c.name }}</td>
        <td class="sev-{{ c.severity }}">{{ c.severity }}</td>
        <td class="{{ 'fail' if c.status == 'FAIL' else 'pass' }}">{{ c.status }}</td>
        <td class="rs-{{ c.run_status }}">{{ c.run_status }}</td>
        <td style="font-size:12px;">{{ c.scope }}</td>
        <td>{{ c.findings }}건</td><td>{{ c.deduction }}점</td>
      </tr>
      {% endfor %}
    </table>
  </div>

  <div class="card">
    <h2 style="margin-top:0; font-size:19px;">카메라별 디코딩</h2>
    <table>
      <tr><th>카메라</th><th>디코딩 성공</th><th>디코딩 실패</th><th>파일 없음</th><th>프레임(전체/표본)</th><th>백엔드</th></tr>
      {% for key, d in r.manifest.video_decode.per_camera.items() %}
      <tr>
        <td><code>{{ key }}</code></td>
        <td>{{ d.episodes_decoded }}개 에피소드</td>
        <td>{{ d.episodes_failed | length }}개</td>
        <td>{{ d.episodes_missing_file | length }}개</td>
        <td>{{ d.frames_decoded_full }} / {{ d.frames_used_sampled }}</td>
        <td>{{ d.backends_used | join(', ') }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>

  <div class="card">
    <h2 style="margin-top:0; font-size:19px;">에피소드별 결함 목록</h2>
    {% if r.findings %}
    <table>
      <tr><th>검사</th><th>에피소드</th><th>심각도</th><th>처분</th><th>내용 (근거 수치 포함)</th></tr>
      {% for f in r.findings %}
      <tr>
        <td><code>{{ f.check }}</code></td>
        <td>{% if f.episode_index is not none %}{{ f.episode_index }}{% if r.summary.repo_id %} · <a href="https://huggingface.co/spaces/lerobot/visualize_dataset?path=/{{ r.summary.repo_id }}/episode_{{ f.episode_index }}" target="_blank" rel="noopener">비주얼라이저</a>{% endif %}{% else %}전체{% endif %}</td>
        <td class="sev-{{ f.severity }}">{{ f.severity }}</td>
        <td>{% if f.episode_index is not none %}<span class="disp-{{ r.dispositions[f.episode_index | string] }}">{{ r.dispositions[f.episode_index | string] }}</span>{% else %}-{% endif %}</td>
        <td>{{ f.detail }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}
    <p>발견된 결함이 없습니다.</p>
    {% endif %}
    {% if r.review_episodes %}
    <p>보류(review) 에피소드 {{ r.review_episodes | length }}개는 review_index.json에 따로 정리했습니다 — 경계 측정값이라 자동 제외하지 않고 사람 확인이 필요합니다.</p>
    {% endif %}
    {% if r.errors %}
    <p class="fail">검사 실행 오류: {{ r.errors }}</p>
    {% endif %}
  </div>

  {% if r.task_scores %}
  <div class="card">
    <h2 style="margin-top:0; font-size:19px;">과제별 점수</h2>
    <table>
      <tr><th>과제</th><th>에피소드</th><th>발견</th><th>감점</th><th>점수</th><th>등급</th></tr>
      {% for t in r.task_scores %}
      <tr>
        <td>{{ t.task }}</td><td>{{ t.episodes }}개</td><td>{{ t.findings }}건</td>
        <td>{{ t.deduction }}점</td><td>{{ t.score }}</td><td>{{ t.grade }}</td>
      </tr>
      {% endfor %}
    </table>
    <p style="font-size:13px; color:#5a6a85;">에피소드 단위 발견만 과제별로 묶었습니다. 데이터셋 단위 발견의 감점 {{ r.dataset_level_deduction }}점은 어느 과제에도 넣지 않았습니다.</p>
  </div>
  {% endif %}

  {% if r.review_shortlist %}
  <div class="card">
    <h2 style="margin-top:0; font-size:19px;">먼저 볼 에피소드 (보류 단축목록)</h2>
    <table>
      <tr><th>순위</th><th>에피소드</th><th>걸린 검사</th><th>jerk p95</th><th>최대 스텝</th><th>정지 비율</th><th>최종 자세 거리(σ)</th><th>이상치 점수</th></tr>
      {% for s in r.review_shortlist %}
      <tr>
        <td>{{ s.rank }}</td>
        <td>{{ s.episode_index }}{% if s.visualizer_url %} · <a href="{{ s.visualizer_url }}" target="_blank" rel="noopener">열어보기</a>{% endif %}</td>
        <td>{{ s.checks | join(', ') }}</td>
        <td>{{ s.metrics.jerk_p95 if s.metrics and s.metrics.jerk_p95 is not none else '-' }}</td>
        <td>{{ s.metrics.max_step if s.metrics and s.metrics.max_step is not none else '-' }}</td>
        <td>{{ '%.0f%%' % (100 * s.metrics.idle_ratio) if s.metrics and s.metrics.idle_ratio is not none else '-' }}</td>
        <td>{{ s.metrics.final_pose_distance if s.metrics and s.metrics.final_pose_distance is not none else '-' }}</td>
        <td>{{ s.outlier_score }}</td>
      </tr>
      {% endfor %}
    </table>
    <p style="font-size:13px; color:#5a6a85;">보류 에피소드를 지표 이상치 순으로 정렬한 목록입니다. 전부를 보지 말고 위에서부터 확인하세요.</p>
    {% if r.delete_commands and r.delete_commands.excluded_command %}
    <p style="font-size:13px;">제외 에피소드 삭제 명령 (RoboAudit는 실행하지 않습니다 — 확인 후 직접 실행하세요):<br>
    <code>{{ r.delete_commands.excluded_command }}</code></p>
    {% endif %}
  </div>
  {% endif %}

  {% if r.notices %}
  <div class="card">
    <h2 style="margin-top:0; font-size:19px;">고지 · 해석 범위</h2>
    <ul style="margin:0; padding-left:20px; line-height:1.8; font-size:14px;">
      {% for n in r.notices %}
      <li>{{ n }}</li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}

  <p style="text-align:center; color:#8a97ad; font-size:12.5px;">
    RoboAudit v{{ r.manifest.tool.version }} · 규칙 {{ r.manifest.rules_version }} · 입력 지문 {{ r.manifest.input_fingerprint.value[:16] }}…<br>
    원본 데이터는 읽기만 했습니다 · 깨끗한 에피소드 목록은 clean_index.json, 보류 목록은 review_index.json 참조
  </p>
</div>
</body>
</html>
""", autoescape=True)


def write_outputs(result: dict, out_dir, markdown: bool = False) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / "report.html"
    html_path.write_text(_TEMPLATE.render(r=result), encoding="utf-8")
    json_path = out / "result.json"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str),
                         encoding="utf-8")
    badge_path = out / "badge.svg"
    badge_path.write_text(render_badge(result), encoding="utf-8")
    paths = {"html": str(html_path), "json": str(json_path),
             "badge": str(badge_path)}
    if markdown:
        md_path = out / "report.md"
        md_path.write_text(render_markdown(result), encoding="utf-8")
        paths["markdown"] = str(md_path)
    clean_index = {
        "dataset": result["summary"]["dataset"],
        "format": result["summary"]["format"],
        "score": result["score"],
        "grade": result["grade"],
        "total_episodes": result["summary"]["total_episodes"],
        "clean_episodes": result["clean_episodes"],
        "excluded_episodes": result["excluded_episodes"],
        "review_episodes": result["review_episodes"],
    }
    ci_path = out / "clean_index.json"
    ci_path.write_text(json.dumps(clean_index, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    review_index = {
        "dataset": result["summary"]["dataset"],
        "format": result["summary"]["format"],
        "score": result["score"],
        "grade": result["grade"],
        "note": "경계 측정값이라 자동 제외하지 않은 에피소드. 사람 확인 후 제외/유지 결정 필요.",
        "review_episodes": result["review_episodes"],
    }
    ri_path = out / "review_index.json"
    ri_path.write_text(json.dumps(review_index, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    paths["clean_index"] = str(ci_path)
    paths["review_index"] = str(ri_path)
    return paths
