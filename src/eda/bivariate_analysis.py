from abc import ABC, abstractmethod  # For implementing the strategy pattern
import matplotlib.pyplot as plt  # For visualization
import pandas as pd  # For handling dataframes
import seaborn as sns  # For statistical visualizations


class BivariateStatisticalAnalysisStrategy(ABC):
    """
    Abstract base class defining the strategy interface for 
    bivariate statistical analysis.
    """

    @abstractmethod
    def render(self, df: pd.DataFrame, feature1: str, feature2: str) -> None:
        """
        Abstract method to be implemented for rendering bivariate analysis.

        :param df: pd.DataFrame - The dataset to analyze.
        :param feature1: str - The first feature for analysis.
        :param feature2: str - The second feature for analysis.
        :return: None
        """
        pass


class NumericalWithNumericalAnalysis(BivariateStatisticalAnalysisStrategy):
    """
    Concrete strategy for analyzing relationships between two numerical features
    using a scatter plot.
    """

    def render(self, df: pd.DataFrame, feature1: str, feature2: str) -> None:
        """
        Generates a scatter plot to visualize the relationship between two numerical features.

        :param df: pd.DataFrame - The dataset to analyze.
        :param feature1: str - The first numerical feature.
        :param feature2: str - The second numerical feature.
        :return: None
        """
        if feature1 not in df.columns or feature2 not in df.columns:
            print(f"Feature '{feature1}' or '{feature2}' not found in the dataset.")
            return

        if not (pd.api.types.is_numeric_dtype(df[feature1]) and pd.api.types.is_numeric_dtype(df[feature2])):
            print(f"Both '{feature1}' and '{feature2}' must be numerical features.")
            return

        plt.figure(figsize=(10, 6))
        sns.scatterplot(x=feature1, y=feature2, data=df)
        plt.title(f"Scatter Plot: {feature1} vs {feature2}")
        plt.xlabel(feature1)
        plt.ylabel(feature2)
        plt.show()


class CategoricalWithNumericalAnalysis(BivariateStatisticalAnalysisStrategy):
    """
    Concrete strategy for analyzing relationships between a categorical 
    and a numerical feature using a box plot.
    """

    def render(self, df: pd.DataFrame, feature1: str, feature2: str) -> None:
        """
        Generates a box plot to visualize the relationship between a categorical 
        and a numerical feature.

        :param df: pd.DataFrame - The dataset to analyze.
        :param feature1: str - The categorical feature.
        :param feature2: str - The numerical feature.
        :return: None
        """
        if feature1 not in df.columns or feature2 not in df.columns:
            print(f"Feature '{feature1}' or '{feature2}' not found in the dataset.")
            return

        if not pd.api.types.is_categorical_dtype(df[feature1]) and df[feature1].nunique() > 30:
            print(f"Feature '{feature1}' has too many unique values, consider grouping categories.")
            return

        if not pd.api.types.is_numeric_dtype(df[feature2]):
            print(f"Feature '{feature2}' must be numerical.")
            return

        plt.figure(figsize=(10, 6))
        sns.boxplot(x=feature1, y=feature2, data=df)
        plt.title(f"Box Plot: {feature1} vs {feature2}")
        plt.xlabel(feature1)
        plt.ylabel(feature2)
        plt.xticks(rotation=45)
        plt.show()


class BivariateAnalysisExecutor:
    """
    Executes bivariate statistical analysis using a selected strategy.
    """

    def __init__(self, strategy: BivariateStatisticalAnalysisStrategy) -> None:
        """
        Initializes the executor with a specific bivariate analysis strategy.

        :param strategy: BivariateStatisticalAnalysisStrategy - The analysis strategy to use.
        """
        self._strategy = strategy

    def configure_strategy(self, strategy: BivariateStatisticalAnalysisStrategy) -> None:
        """
        Configures a different analysis strategy.

        :param strategy: BivariateStatisticalAnalysisStrategy - The new strategy to use.
        :return: None
        """
        self._strategy = strategy

    def run_analysis(self, df: pd.DataFrame, feature1: str, feature2: str) -> None:
        """
        Executes the analysis using the configured strategy.

        :param df: pd.DataFrame - The dataset to analyze.
        :param feature1: str - The first feature for analysis.
        :param feature2: str - The second feature for analysis.
        :return: None
        """
        self._strategy.render(df, feature1, feature2)
