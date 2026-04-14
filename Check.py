import sys

def _require(pkg, import_name=None):
    """Import a dependency or print a helpful install message."""
    name = import_name or pkg
    try:
        return __import__(name)
    except ModuleNotFoundError:
        print(f"Missing dependency: {pkg}")
        print(f"Install it with:\n  python3 -m pip install {pkg}")
        sys.exit(1)

pd = _require("pandas")
xgb = _require("xgboost")
sklearn = _require("scikit-learn", "sklearn")

print(f"Pandas version: {pd.__version__}")
print(f"XGBoost version: {xgb.__version__}")
print(f"Scikit-learn version: {sklearn.__version__}")
print("Environment is ready for PdM development.")
