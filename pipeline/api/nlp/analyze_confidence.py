import pandas as pd
import numpy as np

# Read the CSV
df = pd.read_csv('llm_evaluation_detailed.csv', sep=';')

# Filter rows with confidence scores
df_conf = df[df['confidence_score'].notna()].copy()

# Identify false positives: predicted something when expected is empty or "[NO EXPECTED ANNOTATION]"
def is_false_positive(row):
    expected = str(row['expected_annotation']) if pd.notna(row['expected_annotation']) else ''
    predicted = str(row['predicted_annotation']) if pd.notna(row['predicted_annotation']) else ''
    
    has_expected = expected.strip() != '' and expected != '[NO EXPECTED ANNOTATION]' and expected != 'nan'
    has_predicted = predicted.strip() != '' and predicted != '[NO PREDICTION]' and predicted != 'nan'
    
    return not has_expected and has_predicted

df_conf['is_false_positive'] = df_conf.apply(is_false_positive, axis=1)

# Categorize predictions
false_positives = df_conf[df_conf['is_false_positive']]
correct_predictions = df_conf[df_conf['overall_match'] == True]
incorrect_predictions = df_conf[(df_conf['overall_match'] == False) & (~df_conf['is_false_positive'])]

print("=" * 80)
print("CONFIDENCE SCORE ANALYSIS")
print("=" * 80)
print(f"\nTotal rows with confidence: {len(df_conf)}")
print(f"False positives: {len(false_positives)}")
print(f"Correct predictions: {len(correct_predictions)}")
print(f"Incorrect predictions (not false positives): {len(incorrect_predictions)}")

print("\n" + "=" * 80)
print("FALSE POSITIVES (predicted when no expected annotation)")
print("=" * 80)
if len(false_positives) > 0:
    print(f"Count: {len(false_positives)}")
    print(f"Mean confidence: {false_positives['confidence_score'].mean():.4f}")
    print(f"Median confidence: {false_positives['confidence_score'].median():.4f}")
    print(f"Min confidence: {false_positives['confidence_score'].min():.4f}")
    print(f"Max confidence: {false_positives['confidence_score'].max():.4f}")
    print(f"25th percentile: {false_positives['confidence_score'].quantile(0.25):.4f}")
    print(f"75th percentile: {false_positives['confidence_score'].quantile(0.75):.4f}")
    print(f"\nConfidence distribution:")
    print(false_positives['confidence_score'].describe())
else:
    print("No false positives found!")

print("\n" + "=" * 80)
print("CORRECT PREDICTIONS")
print("=" * 80)
if len(correct_predictions) > 0:
    print(f"Count: {len(correct_predictions)}")
    print(f"Mean confidence: {correct_predictions['confidence_score'].mean():.4f}")
    print(f"Median confidence: {correct_predictions['confidence_score'].median():.4f}")
    print(f"Min confidence: {correct_predictions['confidence_score'].min():.4f}")
    print(f"Max confidence: {correct_predictions['confidence_score'].max():.4f}")
    print(f"25th percentile: {correct_predictions['confidence_score'].quantile(0.25):.4f}")
    print(f"75th percentile: {correct_predictions['confidence_score'].quantile(0.75):.4f}")
    print(f"\nConfidence distribution:")
    print(correct_predictions['confidence_score'].describe())

print("\n" + "=" * 80)
print("INCORRECT PREDICTIONS (not false positives)")
print("=" * 80)
if len(incorrect_predictions) > 0:
    print(f"Count: {len(incorrect_predictions)}")
    print(f"Mean confidence: {incorrect_predictions['confidence_score'].mean():.4f}")
    print(f"Median confidence: {incorrect_predictions['confidence_score'].median():.4f}")
    print(f"Min confidence: {incorrect_predictions['confidence_score'].min():.4f}")
    print(f"Max confidence: {incorrect_predictions['confidence_score'].max():.4f}")
    print(f"25th percentile: {incorrect_predictions['confidence_score'].quantile(0.25):.4f}")
    print(f"75th percentile: {incorrect_predictions['confidence_score'].quantile(0.75):.4f}")
    print(f"\nConfidence distribution:")
    print(incorrect_predictions['confidence_score'].describe())

print("\n" + "=" * 80)
print("THRESHOLD RECOMMENDATIONS")
print("=" * 80)

if len(false_positives) > 0:
    # Calculate what threshold would catch different percentages of false positives
    fp_scores = false_positives['confidence_score'].sort_values()
    
    print("\nThresholds to reject different percentages of false positives:")
    for pct in [50, 75, 90, 95, 99]:
        threshold = fp_scores.quantile(pct / 100.0)
        would_reject = len(fp_scores[fp_scores <= threshold])
        print(f"  {pct}% of false positives: threshold = {threshold:.4f} (would reject {would_reject}/{len(fp_scores)} false positives)")
    
    # Calculate impact on correct predictions
    if len(correct_predictions) > 0:
        print("\nImpact on correct predictions at different thresholds:")
        for threshold in [-0.5, -0.4, -0.3, -0.2, -0.1]:
            fp_rejected = len(false_positives[false_positives['confidence_score'] <= threshold])
            correct_rejected = len(correct_predictions[correct_predictions['confidence_score'] <= threshold])
            print(f"  Threshold {threshold:.1f}:")
            print(f"    - Rejects {fp_rejected}/{len(false_positives)} false positives ({100*fp_rejected/len(false_positives):.1f}%)")
            print(f"    - Rejects {correct_rejected}/{len(correct_predictions)} correct predictions ({100*correct_rejected/len(correct_predictions):.1f}%)")
            print(f"    - Total rejected: {fp_rejected + correct_rejected}")

# Per-prompt-type analysis
print("\n" + "=" * 80)
print("PER-PROMPT-TYPE ANALYSIS")
print("=" * 80)
for prompt_type in df_conf['prompt_type'].unique():
    df_pt = df_conf[df_conf['prompt_type'] == prompt_type]
    fp_pt = df_pt[df_pt['is_false_positive']]
    correct_pt = df_pt[df_pt['overall_match'] == True]
    
    print(f"\n{prompt_type}:")
    print(f"  Total: {len(df_pt)}")
    print(f"  False positives: {len(fp_pt)}")
    if len(fp_pt) > 0:
        print(f"    Mean confidence: {fp_pt['confidence_score'].mean():.4f}")
        print(f"    Min confidence: {fp_pt['confidence_score'].min():.4f}")
        print(f"    Max confidence: {fp_pt['confidence_score'].max():.4f}")
    if len(correct_pt) > 0:
        print(f"  Correct predictions: {len(correct_pt)}")
        print(f"    Mean confidence: {correct_pt['confidence_score'].mean():.4f}")

