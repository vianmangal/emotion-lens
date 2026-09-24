<div align="center">

# EmotionLens

**A full-stack facial-expression classifier for uploaded images and webcam captures.**

Built with TensorFlow, FastAPI, React, PostgreSQL, and AWS infrastructure as code.

</div>

EmotionLens detects the largest visible face, converts it to the model's `48 × 48` grayscale input, and predicts one of five expression classes: **angry**, **fear**, **happy**, **neutral**, or **sad**. The application supports file uploads and webcam captures, returns confidence scores for every class, and stores prediction records in PostgreSQL.

> [!IMPORTANT]
> Facial-expression classification is probabilistic and can be affected by lighting, pose, image quality, demographic bias, and the training data. EmotionLens is an educational project—not a medical, psychological, safety, employment, or identity-assessment tool.

## Features

- Upload JPG, PNG, or WebP images up to 5 MiB and 4096 × 4096 pixels through a responsive drag-and-drop interface.
- Capture a frame directly from the browser using the webcam.
- Reject images without a detected face; when several faces are present, outline the largest face used for inference.
- Return the predicted class, confidence, all class scores, face-detection status, and model version.
- Persist prediction metadata through an asynchronous FastAPI and PostgreSQL data layer.
- Train, evaluate, inspect misclassifications, predict individual files, or run local webcam inference from Python scripts.
- Provision a production AWS stack with Terraform and deploy through GitHub Actions.

## Model snapshot

The latest checked-in evaluation report covers 6,236 samples:

| Metric | Score |
| --- | ---: |
| Accuracy | 61.45% |
| Macro F1 | 59.03% |
| Weighted F1 | 61.76% |
| Best-performing class | Happy — 84.65% F1 |


These numbers describe one stored evaluation run and should not be interpreted as general real-world reliability.

## Architecture

```text
React + Vite UI
      |
      | image upload / webcam frame
      v
FastAPI /predict
      |
      +--> OpenCV face detection and 48x48 preprocessing
      +--> TensorFlow CNN inference
      +--> PostgreSQL prediction record
      |
      v
Prediction, confidence, class scores, and model metadata
```

Production infrastructure is defined in Terraform and uses CloudFront, S3, WAF, an HTTPS Application Load Balancer, ECS Fargate, ECR, RDS PostgreSQL, Secrets Manager, KMS, private networking, and GitHub Actions with AWS OIDC.

## Tech stack

| Area | Technology |
| --- | --- |
| Model | TensorFlow / Keras CNN |
| Image processing | OpenCV, NumPy |
| API | FastAPI, Gunicorn, Uvicorn |
| Persistence | PostgreSQL, SQLAlchemy async, Alembic |
| Frontend | React, Vite, Tailwind CSS, React Webcam |
| Local infrastructure | Docker Compose |
| Cloud infrastructure | AWS, Terraform, GitHub Actions |

## Run the application locally

### Prerequisites

- Python 3.11 recommended
- Node.js 18 or newer
- npm
- Docker with Docker Compose

### 1. Clone and install the backend

```bash
git clone https://github.com/vianmangal/emotion-lens.git
cd emotion-lens

python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

On Windows, activate the environment with `.venv\Scripts\activate`.

### 2. Start PostgreSQL

```bash
docker compose up -d db
```

### 3. Configure the API

Create a root `.env` file:

```dotenv
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/emotiondb
MODEL_PATH=models/emotion_cnn_20260530_193721_best.keras
CORS_ALLOW_ORIGINS=["http://localhost:5173"]
```

Apply the database migration and start FastAPI:

```bash
alembic upgrade head
uvicorn backend.main:app --reload
```

The health endpoint is available at `http://localhost:8000/health`.

### 4. Start the frontend

In a second terminal:

```bash
cd deep_fe/frontend
npm ci
```

Create `deep_fe/frontend/.env.local`:

```dotenv
VITE_API_URL=http://localhost:8000
```

Then run:

```bash
npm run dev
```

Open the URL printed by Vite and choose image upload or webcam capture.

## API

### `POST /predict`

Send an image as multipart form data under the `image` field:

```bash
curl -X POST http://localhost:8000/predict \
  -F "image=@path/to/face.jpg"
```

Example response shape:

```json
{
  "emotion": "happy",
  "confidence": 0.91,
  "all_scores": {
    "angry": 0.01,
    "fear": 0.02,
    "happy": 0.91,
    "neutral": 0.04,
    "sad": 0.02
  },
  "face_detected": true,
  "face_box": {"x": 12, "y": 8, "width": 30, "height": 32},
  "face_count": 2,
  "image_width": 640,
  "image_height": 480,
  "model_version": "emotion_cnn_20260530_193721_best.keras"
}
```

Uploads are limited to 5 MiB and 4096 × 4096 pixels. The API accepts actual JPEG, PNG, and WebP image data. Invalid files and images without a detected face return a `400` response; files over 5 MiB return `413`. The bounding box uses pixel coordinates in the decoded image, and `face_count` reports how many faces were detected.

### `GET /health`

Returns the API status and whether the model loaded successfully.

## Model tooling

The standalone scripts under `src/` support the model-development workflow. Install the additional training and analysis packages when needed:

```bash
pip install tensorflow opencv-python matplotlib pandas numpy scikit-learn
```

```bash
# Train
python src/train.py

# Evaluate the latest model
python src/evaluate.py

# Predict one image
python src/predict.py --image-path path/to/face.jpg

# Run real-time local webcam inference; press q to quit
python src/webcam.py
```

The repository references the [Emotions dataset](https://www.kaggle.com/datasets/nelgiriyewithana/emotions) and [FER-2013](https://www.kaggle.com/datasets/msambare/fer2013) for experimentation.

## Repository structure

```text
emotion-lens/
├── backend/              # FastAPI application, inference, persistence, and container
├── deep_fe/frontend/     # React application
├── infra/                # Terraform AWS infrastructure
├── migrations/           # Alembic database migrations
├── models/               # Model artifacts and evaluation reports
├── src/                  # Training, evaluation, prediction, and webcam scripts
├── docker-compose.yml    # Local PostgreSQL
└── DEPLOY.md             # Production deployment and migration guide
```

## Deployment

See [`DEPLOY.md`](DEPLOY.md) for the AWS prerequisites, encrypted Terraform state setup, model upload, database migration, GitHub Actions secrets, and production rollout steps.

Review every Terraform plan before applying it. Existing RDS and ECR resources require controlled migrations when changing encryption settings.

## Privacy

The API stores the image filename, prediction, confidence, and class scores. Review the schema and retention requirements before deploying publicly, and do not retain or process facial images without appropriate user notice and consent.
