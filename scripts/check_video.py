"""Read-only media checks. Requires ffprobe; --decode also requires ffmpeg."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video', type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--expect-width', type=int)
    parser.add_argument('--expect-height', type=int)
    parser.add_argument('--expect-fps', type=float)
    parser.add_argument('--expect-duration', type=float)
    parser.add_argument('--decode', action='store_true')
    args = parser.parse_args()
    source = args.video.resolve()
    if source == args.report.resolve():
        parser.error('Report must not overwrite the input video.')
    report = {'input': str(source), 'ok': False, 'errors': [],
              'full_decode': 'not_requested', 'visual_review': 'not_performed',
              'subtitle_review': 'not_performed', 'listening_review': 'not_performed'}
    try:
        if not source.is_file():
            raise FileNotFoundError(f'Input not found: {source}')
        probe = shutil.which('ffprobe')
        if not probe:
            raise RuntimeError('ffprobe is not on PATH; install FFmpeg or add its bin directory.')
        process = subprocess.run([probe, '-v', 'error', '-show_streams', '-show_format',
                                  '-of', 'json', str(source)], check=True,
                                 capture_output=True, text=True, encoding='utf8')
        meta = json.loads(process.stdout)
        videos = [s for s in meta['streams'] if s['codec_type'] == 'video'
                  and not s.get('disposition', {}).get('attached_pic')]
        if not videos:
            raise RuntimeError('No video stream found.')
        v = videos[0]
        rate = v.get('avg_frame_rate', '0/1')
        fps = float(Fraction(rate)) if rate not in ('0/0', 'N/A') else 0
        duration_raw = v.get('duration', meta.get('format', {}).get('duration'))
        duration = float(duration_raw) if duration_raw not in (None, 'N/A') else None
        report.update(width=v['width'], height=v['height'], fps=fps, duration=duration,
                      declared_frame_count=v.get('nb_frames'), codec=v['codec_name'],
                      pixel_format=v.get('pix_fmt'), sample_aspect_ratio=v.get('sample_aspect_ratio'),
                      audio_streams=[{'codec': s['codec_name'], 'channels': s.get('channels'),
                                      'sample_rate': s.get('sample_rate')}
                                     for s in meta['streams'] if s['codec_type'] == 'audio'],
                      file_bytes=source.stat().st_size)
        for key, expected, tolerance in [('width', args.expect_width, 0),
                                         ('height', args.expect_height, 0),
                                         ('fps', args.expect_fps, .01),
                                         ('duration', args.expect_duration, .05)]:
            actual = report[key]
            if expected is not None and (actual is None or abs(actual - expected) > tolerance):
                report['errors'].append(f'{key}: expected {expected}, found {actual}')
        if args.decode:
            ffmpeg = shutil.which('ffmpeg')
            if not ffmpeg:
                raise RuntimeError('ffmpeg is not on PATH; full decode could not run.')
            p = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', str(source),
                                '-map', '0:v:0', '-map', '0:a?', '-f', 'null', '-'],
                               capture_output=True, text=True, encoding='utf8', errors='replace')
            report['full_decode'] = 'passed' if p.returncode == 0 else 'failed'
            if p.returncode:
                report['errors'].append(p.stderr[-4000:] or 'Decode failed without details.')
        report['ok'] = not report['errors']
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as error:
        report['errors'].append(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(('PASS' if report['ok'] else 'FAIL') + ': ' + str(args.report))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
