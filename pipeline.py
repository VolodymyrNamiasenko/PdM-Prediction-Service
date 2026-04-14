"""
Feature Engineering Pipeline + XGBoost Retraining for CAB-INS02 Breakdown Prediction

Key insight: the original model only saw raw sensor snapshots.
This pipeline adds temporal features (deltas, acceleration, rolling stats)
so the model can distinguish slow drift from accelerating pre-failure.

Label strategy:
  0 = Healthy (no breakdown developing)
  1 = Pre-failure (breakdown is developing, will arrive within ~30 min)
  
We use maintenance_required as the ground truth transition point.
"""

import json
import glob
import numpy as np
import pandas as pd
from collections import OrderedDict

# ============================================================
# 1. RAW FEATURE LIST
# ============================================================

RAW_FEATURES = [
    'pvc_screw_pressure_bar',
    'color_screw_pressure_bar',
    'nylon_screw_pressure_bar',
    'pvc_screw_speed_rpm',
    'color_screw_speed_rpm',
    'nylon_screw_speed_rpm',
    'motor_load_amps',
    'motor_load_percent',
    'line_speed_m_min',
    'payoff_tension_n',
    'takeup_tension_n',
    'post_extrusion_diameter_mm',
]

# ============================================================
# 2. LOAD AND PARSE ALL BREAKDOWN FILES
# ============================================================

def load_breakdown_files(pattern='/mnt/user-data/uploads/breakdown_*.json'):
    """Load all breakdown event files into a list of DataFrames."""
    files = sorted(glob.glob(pattern))
    all_events = []
    
    for fp in files:
        with open(fp) as f:
            records = json.load(f)
        
        rows = []
        for r in records:
            row = {'timestamp': r['timestamp'], 'machine_id': r['machine_id']}
            row.update(r['features'])
            rows.append(row)
        
        df = pd.DataFrame(rows)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['event_file'] = fp.split('/')[-1]
        
        # Label: 1 if maintenance_required == 1 (pre-failure phase)
        # This marks the last 30 min before breakdown
        df['label'] = (df['maintenance_required'] == 1).astype(int)
        
        all_events.append(df)
    
    return all_events


# ============================================================
# 3. TEMPORAL FEATURE ENGINEERING
# ============================================================

def add_temporal_features(df, lookback_windows=[6, 18, 30, 60]):
    """
    Add temporal features to a single time-series DataFrame.
    
    For each raw feature, computes:
      - delta_{W}:   value - value_W_steps_ago  (rate of change)
      - accel_{W}:   delta_now - delta_W_steps_ago  (acceleration)
      - rollmean_{W}: rolling mean over W steps
      - rollstd_{W}:  rolling std over W steps
      - dev_{W}:     (value - rollmean_W) / rollstd_W  (z-score deviation)
    
    Lookback windows (in steps of 10s):
      6  = 1 minute
      18 = 3 minutes
      30 = 5 minutes
      60 = 10 minutes
    """
    
    df = df.copy()
    
    # Build all new columns in a dict, then concat once (avoids fragmentation)
    new_cols = {}
    
    for feat in RAW_FEATURES:
        series = df[feat]
        for w in lookback_windows:
            # --- Rate of change (delta) ---
            delta = series - series.shift(w)
            new_cols[f'{feat}__delta_{w}'] = delta
            
            # --- Acceleration (second derivative) ---
            new_cols[f'{feat}__accel_{w}'] = delta - delta.shift(w)
            
            # --- Rolling mean ---
            rmean = series.rolling(window=w, min_periods=1).mean()
            new_cols[f'{feat}__rmean_{w}'] = rmean
            
            # --- Rolling std ---
            rstd = series.rolling(window=w, min_periods=2).std()
            new_cols[f'{feat}__rstd_{w}'] = rstd
            
            # --- Z-score deviation from rolling mean ---
            new_cols[f'{feat}__zdev_{w}'] = np.where(
                rstd > 0.001,
                (series - rmean) / rstd,
                0.0
            )
    
    # --- Cross-feature interaction terms ---
    pvc_psr = df['pvc_screw_pressure_bar'] / df['pvc_screw_speed_rpm'].clip(lower=1)
    color_psr = df['color_screw_pressure_bar'] / df['color_screw_speed_rpm'].clip(lower=1)
    nylon_psr = df['nylon_screw_pressure_bar'] / df['nylon_screw_speed_rpm'].clip(lower=1)
    motor_eff = df['motor_load_percent'] / df['line_speed_m_min'].clip(lower=0.1)
    tension_imb = df['payoff_tension_n'] - df['takeup_tension_n']
    dia_dev = df['post_extrusion_diameter_mm'] - 8.20
    
    new_cols['pvc_pressure_speed_ratio'] = pvc_psr
    new_cols['color_pressure_speed_ratio'] = color_psr
    new_cols['nylon_pressure_speed_ratio'] = nylon_psr
    new_cols['motor_efficiency'] = motor_eff
    new_cols['tension_imbalance'] = tension_imb
    new_cols['diameter_deviation'] = dia_dev
    
    # --- Temporal interaction terms (deltas of cross-features) ---
    for w in [6, 30]:
        new_cols[f'pvc_pressure_speed_ratio__delta_{w}'] = pvc_psr - pvc_psr.shift(w)
        new_cols[f'motor_efficiency__delta_{w}'] = motor_eff - motor_eff.shift(w)
        new_cols[f'tension_imbalance__delta_{w}'] = tension_imb - tension_imb.shift(w)
        new_cols[f'diameter_deviation__delta_{w}'] = dia_dev - dia_dev.shift(w)
    
    # Single concat — no fragmentation warnings
    df = pd.concat([df, pd.DataFrame(new_cols, index=df.index)], axis=1)
    
    return df


def get_feature_columns(df):
    """Return list of all engineered feature column names (excluding metadata/labels)."""
    exclude = {'timestamp', 'machine_id', 'event_file', 'label',
                'machine_status', 'maintenance_required', 'brake_down'}
    return [c for c in df.columns if c not in exclude]


# ============================================================
# 4. BUILD TRAINING DATASET
# ============================================================

def build_training_data(events, min_lookback=60):
    """
    Process all event DataFrames, add temporal features,
    drop warmup rows (first `min_lookback` records), and concatenate.
    
    Returns X (features), y (labels), and metadata.
    """
    processed = []
    
    for df in events:
        enriched = add_temporal_features(df)
        # Drop warmup rows where lookback features are NaN
        enriched = enriched.iloc[min_lookback:].reset_index(drop=True)
        processed.append(enriched)
    
    combined = pd.concat(processed, ignore_index=True)
    
    feature_cols = get_feature_columns(combined)
    
    X = combined[feature_cols].values
    y = combined['label'].values
    meta = combined[['timestamp', 'machine_id', 'event_file']].copy()
    
    # Handle any remaining NaN/inf
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    
    return X, y, feature_cols, meta


# ============================================================
# 5. TRAIN / EVALUATE
# ============================================================

def train_and_evaluate():
    """Full pipeline: load, engineer, train, evaluate with leave-one-out CV."""
    import xgboost as xgb
    from sklearn.metrics import (
        classification_report, confusion_matrix, 
        roc_auc_score, precision_recall_curve, average_precision_score
    )
    
    print("=" * 80)
    print("LOADING DATA")
    print("=" * 80)
    
    events = load_breakdown_files()
    print(f"Loaded {len(events)} breakdown event files")
    
    # ---- Leave-one-event-out cross-validation ----
    # This is the fairest test: train on 13 events, predict the held-out event
    
    print("\n" + "=" * 80)
    print("LEAVE-ONE-EVENT-OUT CROSS-VALIDATION")
    print("=" * 80)
    
    all_y_true = []
    all_y_pred = []
    all_y_prob = []
    all_meta = []
    
    for hold_out_idx in range(len(events)):
        # Split
        train_events = [e for i, e in enumerate(events) if i != hold_out_idx]
        test_event = [events[hold_out_idx]]
        
        # Build features
        X_train, y_train, feat_cols, _ = build_training_data(train_events)
        X_test, y_test, _, test_meta = build_training_data(test_event)
        
        # Train XGBoost
        model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=5,
            scale_pos_weight=len(y_train[y_train==0]) / max(len(y_train[y_train==1]), 1),
            eval_metric='logloss',
            random_state=42,
            verbosity=0,
        )
        model.fit(X_train, y_train)
        
        # Predict
        y_prob = model.predict_proba(X_test)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)
        
        all_y_true.extend(y_test)
        all_y_pred.extend(y_pred)
        all_y_prob.extend(y_prob)
        all_meta.append(test_meta)
        
        event_name = events[hold_out_idx]['event_file'].iloc[0][:40]
        auc = roc_auc_score(y_test, y_prob) if len(set(y_test)) > 1 else 0
        print(f"  Fold {hold_out_idx+1:2d} ({event_name}): AUC={auc:.4f}")
    
    all_y_true = np.array(all_y_true)
    all_y_pred = np.array(all_y_pred)
    all_y_prob = np.array(all_y_prob)
    
    print("\n" + "=" * 80)
    print("AGGREGATE CV RESULTS")
    print("=" * 80)
    
    print(f"\nROC-AUC: {roc_auc_score(all_y_true, all_y_prob):.4f}")
    print(f"Average Precision: {average_precision_score(all_y_true, all_y_prob):.4f}")
    
    print(f"\nClassification Report (threshold=0.5):")
    print(classification_report(all_y_true, all_y_pred, 
                                 target_names=['Healthy', 'Pre-failure']))
    
    print(f"Confusion Matrix:")
    cm = confusion_matrix(all_y_true, all_y_pred)
    print(f"  TN={cm[0,0]:5d}  FP={cm[0,1]:5d}")
    print(f"  FN={cm[1,0]:5d}  TP={cm[1,1]:5d}")
    
    # ---- Train final model on ALL data ----
    print("\n" + "=" * 80)
    print("TRAINING FINAL MODEL ON ALL DATA")
    print("=" * 80)
    
    X_all, y_all, feat_cols, _ = build_training_data(events)
    
    final_model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        scale_pos_weight=len(y_all[y_all==0]) / max(len(y_all[y_all==1]), 1),
        eval_metric='logloss',
        random_state=42,
        verbosity=0,
    )
    final_model.fit(X_all, y_all)
    
    print(f"Training samples: {len(X_all)} ({sum(y_all==0)} healthy, {sum(y_all==1)} pre-failure)")
    print(f"Features: {len(feat_cols)}")
    
    # ---- Feature importance ----
    print("\n" + "=" * 80)
    print("TOP 30 FEATURES BY IMPORTANCE")
    print("=" * 80)
    
    importances = final_model.feature_importances_
    feat_imp = sorted(zip(feat_cols, importances), key=lambda x: -x[1])
    
    for i, (fname, imp) in enumerate(feat_imp[:30]):
        bar = '█' * int(imp / feat_imp[0][1] * 40)
        print(f"  {i+1:2d}. {fname:50s} {imp:.4f} {bar}")
    
    # Count how many temporal vs raw features in top 30
    temporal_count = sum(1 for f, _ in feat_imp[:30] if '__' in f)
    raw_count = 30 - temporal_count
    print(f"\n  Top 30 breakdown: {temporal_count} temporal features, {raw_count} raw features")
    
    # ---- Save model and feature list ----
    final_model.save_model('/home/claude/xgb_cab_ins02_v2.json')
    
    with open('/home/claude/feature_columns.json', 'w') as f:
        json.dump(feat_cols, f, indent=2)
    
    print(f"\nModel saved: xgb_cab_ins02_v2.json")
    print(f"Feature list saved: feature_columns.json")
    
    return final_model, feat_cols, all_y_true, all_y_prob


if __name__ == '__main__':
    model, feat_cols, y_true, y_prob = train_and_evaluate()