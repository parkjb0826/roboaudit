"""RoboAudit CLI.

사용법:
  python -m roboaudit <dataset_dir> --out <dir> [--sample-frames N]
                      [--share-bundle]
  python -m roboaudit share <result.json> [--out <share_bundle.json>]

출력: report.html / result.json / clean_index.json / review_index.json
      (--share-bundle 시 share_bundle.json 추가)

공유 묶음(share bundle)은 동의 기반(opt-in) 익명 요약이다. 자동 전송은
없고, 기본값은 OFF이며, 데이터셋 이름·경로·과제 원문은 포함되지 않는다
(share.py 참조).

종료 코드:
  0 = 감사 완료 (전 검사가 전체 범위를 검사함; 결함 발견 여부와 무관)
  3 = 감사는 끝났으나 불완전 (일부 검사가 부분 실행/오류 — 성적표에 명시됨)
  2 = 입력 오류 (데이터셋 폴더·meta/info.json 없음, 출력 폴더가 데이터셋 안쪽,
      share 대상 result.json 없음/형식 오류)
  1 = 예상하지 못한 실행 실패
"""
import argparse
import json
import sys
from pathlib import Path

from .audit import audit_dataset
from .report import write_outputs
from .share import bundle_from_result_file, write_bundle


def _share_main(argv):
    """`roboaudit share <result.json>` — 기존 결과에서 익명 묶음 생성."""
    ap = argparse.ArgumentParser(
        prog="roboaudit share",
        description="감사 결과(result.json)에서 동의 기반 익명 공유 "
                    "묶음(share_bundle.json)을 만든다. 전송은 하지 않는다.")
    ap.add_argument("result_json", help="감사 출력 폴더의 result.json 경로")
    ap.add_argument("--out", default=None,
                    help="묶음 출력 경로 (기본: result.json 옆 share_bundle.json)")
    args = ap.parse_args(argv)
    src = Path(args.result_json)
    if not src.exists():
        print(f"error: {src} 가 없습니다", file=sys.stderr)
        return 2
    try:
        bundle = bundle_from_result_file(src)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"error: result.json을 읽을 수 없습니다: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else src.parent / "share_bundle.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"share_bundle: {out}")
    print("이 파일은 익명 요약만 담고 있으며, 어디에도 자동 전송되지 "
          "않습니다. 제출 여부는 본인이 결정하세요.")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "share":
        return _share_main(argv[1:])
    ap = argparse.ArgumentParser(prog="roboaudit",
                                 description="LeRobot 데이터셋 건강검진")
    ap.add_argument("dataset", help="LeRobot 데이터셋 폴더 (v2.1 / v3.0)")
    ap.add_argument("--out", default=None,
                    help="출력 폴더 (기본: <dataset>_audit)")
    ap.add_argument("--sample-frames", type=int, default=None,
                    help="표본 모드: 에피소드당 영상 통계를 최대 N프레임 "
                         "균등 표본으로 계산 (대용량용, 기본: 전수)")
    ap.add_argument("--share-bundle", action="store_true",
                    help="동의 기반 익명 공유 묶음(share_bundle.json)도 "
                         "출력 폴더에 생성 (기본: 생성 안 함, 전송 없음)")
    args = ap.parse_args(argv)

    root = Path(args.dataset)
    if not (root / "meta" / "info.json").exists():
        print(f"error: {root} 에 meta/info.json 이 없습니다", file=sys.stderr)
        return 2
    out_dir = Path(args.out) if args.out else Path(f"{root.name}_audit")
    # 배포 안전 (추가 검토 4): 출력이 입력 데이터셋 안쪽이면 원본을 오염시키므로 거부.
    root_resolved = root.resolve()
    out_resolved = out_dir.resolve()
    if out_resolved == root_resolved or root_resolved in out_resolved.parents:
        print(f"error: 출력 폴더({out_dir})가 데이터셋 폴더({root}) 안쪽입니다. "
              "원본 오염 방지를 위해 거부합니다 — 데이터셋 바깥 폴더를 지정하세요",
              file=sys.stderr)
        return 2
    try:
        result = audit_dataset(root, sample_frames=args.sample_frames)
    except Exception as exc:
        print(f"error: 감사 실행 실패: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1
    paths = write_outputs(result, out_dir)
    if args.share_bundle:
        paths["share_bundle"] = str(write_bundle(
            result, out_dir / "share_bundle.json"))
    s = result["summary"]
    print(f"dataset : {s['dataset']} (LeRobot {s['format']}, "
          f"{s['total_episodes']} episodes)")
    print(f"score   : {result['score']}/100  grade {result['grade']}  "
          f"(deduction {result['total_deduction']}, findings {len(result['findings'])})")
    print(f"clean   : {len(result['clean_episodes'])} episodes / "
          f"excluded {len(result['excluded_episodes'])} / "
          f"review {len(result['review_episodes'])}")
    if result["incomplete_audit"]:
        print("warning : 불완전한 감사 — 일부 검사가 전체 범위를 검사하지 "
              "못했습니다 (성적표 실행 상태 참조)", file=sys.stderr)
    for k, v in paths.items():
        print(f"{k:11s}: {v}")
    if result["errors"]:
        print(f"errors  : {result['errors']}", file=sys.stderr)
    return 3 if result["incomplete_audit"] else 0


if __name__ == "__main__":
    sys.exit(main())
