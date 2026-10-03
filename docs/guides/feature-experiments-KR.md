# 기능별 성능 실험

기능별 구현은 HTTP 요청 경로를 공유하고 스케줄링과 모델 상태 처리는 각 엔진에서 담당합니다.

## 소스 경계

| 모듈 | 역할 |
| --- | --- |
| `src/inference/api.py` | 요청 검증, SSE, 취소와 응답 토큰 집계 |
| `src/inference/contracts.py` | 엔진 인터페이스, 생성 요청과 결과 타입 |
| `src/inference/cache.py` | RAM과 디스크의 snapshot 저장, 조회와 퇴출 |
| `src/inference/metrics.py` | 선택적으로 활성화하는 요청과 생성 지표 |
| `src/huggingface/runtime/` | 모델 간 공통 직렬 생성, 배치 큐, 샘플링과 서버 설정 |
| `src/huggingface/{llama,mamba,jamba}/` | 모델 로딩과 기본값, baseline과 기능별 구현 |
| `src/llamacpp/{base,batch,cache,metrics}/` | GGUF 추론과 선택적 지표 수집 |

```text
src/
├── inference/
├── huggingface/
│   ├── runtime/
│   ├── llama/      # base, batch/gpu, cache, metrics, inference_distributed
│   ├── mamba/      # base, cache
│   └── jamba/      # base, hybrid
└── llamacpp/       # base, batch, cache, metrics
```

각 Hugging Face 모델 계열은 `model.py`에서 로딩을, `serving.py`에서 HTTP 기본값을 정의합니다. `base/`는 직렬 비교 진입점을 제공합니다. 기능별 구현은 같은 계열의 모델과 `runtime/`을 사용하며, 공통 코드는 비교 진입점이나 다른 모델 계열을 import하지 않습니다. 패키지 이름은 설치된 `transformers` 라이브러리와 구분되도록 `huggingface`를 사용합니다.

엔진은 `prepare_prompt`, `complete`, `stream`, `close`를 구현합니다. `stream`은 callback으로 텍스트를 전달하고 토큰 수와 종료 사유를 반환합니다. `complete`는 텍스트도 반환합니다. Executor는 서버 설정에서 생성하여 직렬과 배치 구현의 동시성 동작을 유지합니다. 지표 수집은 metric 진입점에서만 활성화합니다.
