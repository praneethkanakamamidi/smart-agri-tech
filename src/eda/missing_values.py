from abc import ABC, abstractmethod

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


class MissingValuesReportTemplate(ABC):
    def missing_values_analysis(self, df: pd.DataFrame):
        self.missing_values_report(df)
        self.missing_values_visualization(df)

    @abstractmethod
    def missing_values_report(self, df: pd.DataFrame):
        pass

    @abstractmethod
    def missing_values_visualization(self, df: pd.DataFrame):
        pass


class MissingValuesReport(MissingValuesReportTemplate):
    def missing_values_report(self, df: pd.DataFrame):
        print("\nMissing Values Count by Column:")
        missing_values = df.isnull().sum()
        print(missing_values[missing_values > 0])

    def missing_values_visualization(self, df: pd.DataFrame):
        print("\nVisualizing Missing Values...")
        plt.figure(figsize=(12, 8))
        sns.heatmap(df.isnull(), cbar=False, cmap="viridis")
        plt.title("Missing Values Heatmap")
        plt.show()


if __name__ == "__main__":
    pass
