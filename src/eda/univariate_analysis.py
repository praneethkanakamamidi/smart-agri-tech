# Importing necessary libraries
from abc import ABC, abstractmethod  # For implementing the strategy pattern
import matplotlib.pyplot as plt  # For visualization
import pandas as pd  # For handling dataframes
import seaborn as sns  # For statistical visualizations

class UnivariateStatisticalAnalysisStrategy(ABC):
    """
    Abstract base class (ABC) defining the strategy interface for 
    univariate statistical analysis.
    """

    @abstractmethod
    def render(self, df: pd.DataFrame, feature: str) -> None:
        """
        Abstract method to be implemented for rendering univariate analysis.

        :param df: pd.DataFrame - The dataset to analyze.
        :param feature: str - The name of the feature to analyze.
        :return: None
        """
        pass


class UnivariateNumericalAnalysis(UnivariateStatisticalAnalysisStrategy):
    """
    Concrete strategy for univariate analysis of numerical features using a histogram.
    """

    def render(self, df: pd.DataFrame, feature: str) -> None:
        """
        Generates a histogram with a KDE curve to visualize the distribution 
        of a numerical feature.

        :param df: pd.DataFrame - The dataset to analyze.
        :param feature: str - The numerical feature to analyze.
        :return: None
        """
        if feature not in df.columns:
            print(f"Feature '{feature}' not found in the dataset.")
            return

        if not pd.api.types.is_numeric_dtype(df[feature]):
            print(f"Feature '{feature}' is not numerical.")
            return

        plt.figure(figsize=(10, 6))
        sns.histplot(df[feature], kde=True, bins=30)
        plt.title(f"Distribution of {feature}")
        plt.xlabel(feature)
        plt.ylabel("Frequency")
        plt.show()


class UnivariateCategoricalAnalysis(UnivariateStatisticalAnalysisStrategy):
    """
    Concrete strategy for univariate analysis of categorical features using a count plot.
    """

    def render(self, df: pd.DataFrame, feature: str) -> None:
        """
        Generates a count plot to visualize the distribution of a categorical feature.

        :param df: pd.DataFrame - The dataset to analyze.
        :param feature: str - The categorical feature to analyze.
        :return: None
        """
        if feature not in df.columns:
            print(f"Feature '{feature}' not found in the dataset.")
            return

        if not pd.api.types.is_categorical_dtype(df[feature]) and df[feature].nunique() > 30:
            print(f"Feature '{feature}' has too many unique values, consider grouping categories.")
            return

        plt.figure(figsize=(10, 6))
        sns.countplot(x=feature, data=df, palette="muted")
        plt.title(f"Distribution of {feature}")
        plt.xlabel(feature)
        plt.ylabel("Count")
        plt.xticks(rotation=45)
        plt.show()


class UnivariateAnalysisExecutor:
    """
    Executes univariate statistical analysis using a selected strategy.
    """

    def __init__(self, strategy: UnivariateStatisticalAnalysisStrategy) -> None:
        """
        Initializes the executor with a specific univariate analysis strategy.

        :param strategy: UnivariateStatisticalAnalysisStrategy - The analysis strategy to use.
        """
        self._strategy = strategy

    def configure_strategy(self, strategy: UnivariateStatisticalAnalysisStrategy) -> None:
        """
        Configures a different analysis strategy.

        :param strategy: UnivariateStatisticalAnalysisStrategy - The new strategy to use.
        :return: None
        """
        self._strategy = strategy

    def run_analysis(self, df: pd.DataFrame, feature: str) -> None:
        """
        Executes the analysis using the configured strategy.

        :param df: pd.DataFrame - The dataset to analyze.
        :param feature: str - The feature to analyze.
        :return: None
        """
        self._strategy.render(df, feature)
