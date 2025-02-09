# Importing necessary libraries
from abc import ABC, abstractmethod  # For implementing the template design pattern
import matplotlib.pyplot as plt  # For visualization
import pandas as pd  # For handling dataframes
import seaborn as sns  # For enhanced statistical visualizations

class MultivariateStatisticalAnalysisTemplate(ABC):
    """
    An abstract base class (ABC) that defines a template for performing 
    multivariate statistical analysis on a dataset.
    """

    def render(self, df: pd.DataFrame) -> None:
        """
        Calls methods for heatmap correlation analysis and pairplot feature analysis.

        :param df: pd.DataFrame - The dataset to analyze.
        :return: None
        """
        self.heatmap_correlation_analysis(df)
        self.pairplot_feature_analysis(df)

    @abstractmethod
    def heatmap_correlation_analysis(self, df: pd.DataFrame) -> None:
        """
        Abstract method for generating a heatmap to analyze feature correlations.

        :param df: pd.DataFrame - The dataset to analyze.
        :return: None
        """
        pass

    @abstractmethod
    def pairplot_feature_analysis(self, df: pd.DataFrame) -> None:
        """
        Abstract method for generating pairplots to visualize relationships between features.

        :param df: pd.DataFrame - The dataset to analyze.
        :return: None
        """
        pass


class SimpleMultivariateStatisticalAnalysis(MultivariateStatisticalAnalysisTemplate):
    """
    A concrete implementation of multivariate statistical analysis 
    using heatmaps and pairplots.
    """

    def heatmap_correlation_analysis(self, df: pd.DataFrame) -> None:
        """
        Generates a correlation heatmap for numerical features.

        :param df: pd.DataFrame - The dataset to analyze.
        :return: None
        """
        if df.empty:
            print("Dataset is empty. No heatmap can be generated.")
            return

        numeric_df = df.select_dtypes(include=['number'])  # Select only numerical columns
        if numeric_df.shape[1] < 2:
            print("Not enough numerical features for correlation analysis.")
            return

        plt.figure(figsize=(12, 10))
        sns.heatmap(numeric_df.corr(), annot=True, fmt=".2f", cmap="coolwarm", linewidths=0.5)
        plt.title("Feature Correlation Heatmap")
        plt.show()

    def pairplot_feature_analysis(self, df: pd.DataFrame) -> None:
        """
        Generates a pairplot to visualize relationships between features.

        :param df: pd.DataFrame - The dataset to analyze.
        :return: None
        """
        if df.empty:
            print("Dataset is empty. No pairplot can be generated.")
            return

        numeric_df = df.select_dtypes(include=['number'])  # Select only numerical columns
        if numeric_df.shape[1] < 2:
            print("Not enough numerical features for pairplot analysis.")
            return

        sns.pairplot(numeric_df)
        plt.suptitle("Pairwise Feature Relationship Plot", y=1.02)
        plt.show()
