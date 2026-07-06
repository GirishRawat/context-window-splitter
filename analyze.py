import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

def run_analysis():
    if not os.path.exists("sbase_results.csv"):
        print("Results file not found.")
        return
        
    df = pd.read_csv("sbase_results.csv")
    
    # Exclude triaged out
    df_active = df[df["triaged_out"] == False].copy()
    
    if len(df_active) == 0:
        print("No active rows yet.")
        return
        
    print("=== Verdict Distribution ===")
    print(df_active["verdict"].value_counts(dropna=False))
    
    # Create the plot
    plt.figure(figsize=(12, 8))
    
    # We want to plot extract-fail (pending), syntax_fail, reject, pass
    # vs complexity and token count
    
    sns.scatterplot(
        data=df_active, 
        x="tokens", 
        y="complexity", 
        hue="verdict",
        palette={"pending": "gray", "syntax_fail": "red", "reject": "orange", "pass": "green", "error": "black"},
        alpha=0.7,
        s=100
    )
    
    plt.title("LLM Optimization Results by Complexity and Token Count", fontsize=16)
    plt.xlabel("Function Token Count", fontsize=12)
    plt.ylabel("Cyclomatic Complexity", fontsize=12)
    plt.grid(True, linestyle="--", alpha=0.6)
    
    plt.savefig("analysis_plot.png", dpi=300, bbox_inches="tight")
    print("Plot saved to analysis_plot.png")

if __name__ == "__main__":
    run_analysis()
